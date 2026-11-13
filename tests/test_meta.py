from datetime import datetime, timedelta, timezone

import httpx
import pytest

from crdeck import api
from crdeck.battles import crawl, load_battles, parse_battle, save_battles
from crdeck.catalog import load_game_data
from crdeck.collection import default_reference_level
from crdeck.loader import load_player
from crdeck.meta import apply_meta, compute_meta, load_battle_meta
from crdeck.scoring import evaluate_cards
from crdeck.solver import SolveRequest, solve
from fake_battles import make_battles, tag

GAME = load_game_data()
CFG = GAME.rules["battle_meta"]
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
RAW = make_battles(1500, now=NOW)
BATTLES = [parse_battle(r, CFG["battle_types"]) for r in RAW]
BM = compute_meta(BATTLES, CFG, now=NOW)


# ---------------------------------------------------------------- lectura de batallas
def test_parse_battle_filters_and_winner():
    b = BATTLES[0]
    assert len(b["decks"]) == 2 and all(len(d["cards"]) == 8 for d in b["decks"])
    assert b["winner"] in (0, 1)
    assert parse_battle({**RAW[0], "type": "friendly"}, CFG["battle_types"]) is None
    two_vs_two = {**RAW[0], "team": RAW[0]["team"] * 2}
    assert parse_battle(two_vs_two, CFG["battle_types"]) is None
    draw = {**RAW[0], "team": [{**RAW[0]["team"][0], "crowns": 1}], "opponent": [{**RAW[0]["opponent"][0], "crowns": 1}]}
    assert parse_battle(draw, CFG["battle_types"])["winner"] is None


def test_crawl_follows_opponents_and_dedupes():
    # #P2 jugó contra #P8 y #P9; #P8 tiene la misma batalla (repetida) y otra contra #PY.
    def battle(t, a, b):
        return {**RAW[0], "battleTime": t, "team": [{**RAW[0]["team"][0], "tag": a}],
                "opponent": [{**RAW[0]["opponent"][0], "tag": b}]}
    logs = {
        "#PPP2": [battle("20261113T100000.000Z", "#PPP2", "#PPP8"), battle("20261113T110000.000Z", "#PPP2", "#PPP9"),
                  {**RAW[1], "type": "friendly"}],
        "#PPP8": [battle("20261113T100000.000Z", "#PPP8", "#PPP2"), battle("20261113T120000.000Z", "#PPP8", "#PPPY")],
        "#PPP9": [],
        "#PPPY": [],
    }
    visited = []

    def fetch(t):
        visited.append(t)
        return logs[t]

    battles, info = crawl(["PPP2"], max_players=3, battle_types=CFG["battle_types"], fetch=fetch, delay=0)
    assert visited == ["#PPP2", "#PPP8", "#PPP9"]            # respeta el máximo de jugadores
    assert len(battles) == 3 and info["players"] == 3        # la batalla repetida cuenta una vez


def test_crawl_skips_missing_players_but_stops_on_key_errors():
    def fetch(t):
        if t == "#PPP2":
            return [RAW[0]]
        raise api.ApiError("Error 404", status=404)

    battles, info = crawl(["PPP2"], max_players=10, battle_types=CFG["battle_types"], fetch=fetch, delay=0)
    assert len(battles) == 1 and info["errors"] == 1      # el rival no existe: se salta y sigue

    def fatal(t):
        raise api.ApiError("Error 403", status=403, fatal=True)

    with pytest.raises(api.ApiError):
        crawl(["PPP2"], battle_types=CFG["battle_types"], fetch=fatal, delay=0)


def test_save_merges_and_drops_old_battles(tmp_path):
    path = tmp_path / "battles.json"
    assert save_battles(BATTLES[:10], path, now=NOW) == 10
    assert save_battles(BATTLES[5:20], path, now=NOW) == 20          # sin repetir
    old = dict(BATTLES[30], key="vieja", time=(NOW - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert save_battles([old], path, max_age_days=28, now=NOW) == 20
    assert "vieja" not in {b["key"] for b in load_battles(path)}


def test_fetch_battlelog(monkeypatch):
    def get(url, headers=None, timeout=None):
        assert url.endswith("/players/%23PPP2/battlelog")
        return httpx.Response(200, json=RAW[:3], request=httpx.Request("GET", url))
    monkeypatch.setattr(api.httpx, "get", get)
    assert len(api.fetch_battlelog("#PPP2", api_key="x" * 50, use_cache=False)) == 3


# ---------------------------------------------------------------- cálculo del meta
def test_strength_recovers_hidden_effects():
    s = {n: c.strength for n, c in BM.cards.items()}
    assert s["Hog Rider"] > 0 > s["Golem"]
    assert s["Hog Rider"] == max(s.values())
    assert 0.3 < BM.level_effect < 0.7          # el efecto real es 0.5


def test_pairs_find_combos_and_incompatible_cards():
    all_pairs = {**CFG, "synergy": {**CFG["synergy"], "max_pairs": 10_000}}
    w = {frozenset((p.a, p.b)): p.weight for p in compute_meta(BATTLES, all_pairs, now=NOW).pairs}
    assert w.get(frozenset(("Lava Hound", "Balloon")), 0) > 0      # siempre van juntas
    assert w.get(frozenset(("Hog Rider", "Golem")), 0) < 0         # casi nunca van juntas


def test_pair_budget_is_split_between_combos_and_conflicts():
    half = CFG["synergy"]["max_pairs"] // 2
    assert len(BM.pairs) <= CFG["synergy"]["max_pairs"]
    assert sum(p.weight > 0 for p in BM.pairs) >= min(half, 50)


def test_old_battles_are_ignored():
    assert compute_meta(BATTLES, CFG, now=NOW + timedelta(days=60)) is None


def test_apply_meta_blends_with_catalog():
    gm = apply_meta(GAME, BM, CFG)
    d = gm.meta_detail
    assert d["Hog Rider"]["final"] > d["Golem"]["final"]
    assert d["Golem"]["final"] < d["Golem"]["catalogo"]
    assert 0 < d["Golem"]["peso_datos"] < 1
    assert "brandnewcard" in gm.unknown_meta                       # carta nueva: meta sale de los datos
    assert GAME.info("Golem").meta == d["Golem"]["catalogo"]        # el catálogo original no cambia
    sources = {s.source for s in gm.synergies}
    assert {"catálogo", "batallas"} <= sources


def test_solver_works_with_battle_meta(tmp_path):
    path = tmp_path / "battles.json"
    save_battles(BATTLES, path, now=NOW)
    gm, bm = load_battle_meta(GAME, path, now=NOW)
    assert bm is not None and bm.n_battles == len(BATTLES)
    player = load_player(GAME, demo=True)
    evals = evaluate_cards(player, gm, default_reference_level(player))
    res = solve(player, gm, evals, SolveRequest(time_limit=10))
    assert res.ok and len(res.decks[0]["cards"]) == 8
    war = solve(player, gm, evals, SolveRequest(n_decks=4, war_unique=True, time_limit=10))
    assert war.ok and len({c for d in war.decks for c in d["cards"]}) == 32


def test_tag_helper_makes_valid_tags():
    assert api.normalize_tag(tag(12345))


# ---------------------------------------------------------------- probabilidad de victoria
def test_win_probability_matches_hidden_effects():
    from fake_battles import DECKS
    hog, lo, hi = BM.win_probability(DECKS["hog"], 0.0)
    golem = BM.win_probability(DECKS["golem"], 0.0)[0]
    bait = BM.win_probability(DECKS["bait"], 0.0)[0]
    assert lo < hog < hi
    assert hog > 0.58 and golem < 0.42 and 0.44 < bait < 0.56     # reales: 64.6%, 35.4%, 50%
    assert BM.win_probability(DECKS["bait"], 1.0)[0] > bait + 0.05  # +1 nivel ayuda


def test_decks_get_win_probability_only_with_battle_data():
    gm = apply_meta(GAME, BM, CFG)
    player = load_player(GAME, demo=True)
    ev = evaluate_cards(player, gm, 15)
    d = solve(player, gm, ev, SolveRequest(time_limit=10)).decks[0]
    assert d["win"] is not None and 0 < d["win"][0] < 1
    d0 = solve(player, GAME, evaluate_cards(player, GAME, 15), SolveRequest(time_limit=10)).decks[0]
    assert d0["win"] is None


# ---------------------------------------------------------------- efecto de pares (realzan juntas)
def test_pair_effect_is_learned_from_battles():
    from fake_battles import make_random_battles
    raw = make_random_battles(3000, now=NOW)
    bm = compute_meta([parse_battle(r, CFG["battle_types"]) for r in raw], CFG, now=NOW)
    effects = {frozenset((p.a, p.b)): p.effect for p in bm.pairs if p.effect is not None}
    planted = effects[frozenset(("Earthquake", "Hog Rider"))]
    others = [e for k, e in effects.items() if k != frozenset(("Earthquake", "Hog Rider"))]
    assert planted > 0.4 and planted > max(others) + 0.2          # real: +0.8; el resto es ruido
    base = ["Hog Rider", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "Fireball"]
    assert bm.win_probability(base + ["Earthquake"], 0)[0] > bm.win_probability(base + ["Zap"], 0)[0] + 0.03

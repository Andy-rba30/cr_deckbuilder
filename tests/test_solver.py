from crdeck.catalog import load_game_data
from crdeck.loader import load_player
from crdeck.scoring import evaluate_cards, level_factor
from crdeck.solver import SolveRequest, solve

GAME = load_game_data()
PLAYER = load_player(GAME, demo=True)
EVALS = evaluate_cards(PLAYER, GAME, 15)


def roles(deck, role):
    return sum(1 for c in deck if role in PLAYER.cards[c].roles)


def check_rules(d):
    r = GAME.rules["deck"]
    assert len(d["cards"]) == 8
    assert 1 <= roles(d["cards"], "win_condition") <= 2
    assert roles(d["cards"], "air_defense") >= 2
    assert sum(PLAYER.cards[c].champion for c in d["cards"]) <= 1
    assert len(d["evos"]) <= r["evo_slots"]
    assert all(PLAYER.cards[c].evo_unlocked for c in d["evos"])


def test_level_factor_penalizes_sensitive_cards_more():
    rules = GAME.rules
    assert level_factor(12, 15, 0.85, rules) < level_factor(12, 15, 0.15, rules)
    assert level_factor(15, 15, 0.85, rules) == 1.0


def test_optimal_deck_respects_rules():
    res = solve(PLAYER, GAME, EVALS, SolveRequest(time_limit=10))
    assert res.ok
    check_rules(res.decks[0])


def test_alternative_is_different():
    a = solve(PLAYER, GAME, EVALS, SolveRequest(time_limit=10)).decks[0]["cards"]
    b = solve(PLAYER, GAME, EVALS, SolveRequest(exclude_decks=[a], time_limit=10)).decks[0]["cards"]
    assert set(a) != set(b)


def test_archetype_core_is_included():
    res = solve(PLAYER, GAME, EVALS, SolveRequest(archetypes=["log_bait"], time_limit=10))
    assert res.ok and "Goblin Barrel" in res.decks[0]["cards"]
    assert "Hog Rider" not in res.decks[0]["cards"]


def test_alternatives_change_at_least_min_diff_cards():
    a = solve(PLAYER, GAME, EVALS, SolveRequest(time_limit=10)).decks[0]["cards"]
    b = solve(PLAYER, GAME, EVALS, SolveRequest(exclude_decks=[a], min_diff=3, time_limit=10)).decks[0]["cards"]
    c = solve(PLAYER, GAME, EVALS, SolveRequest(exclude_decks=[a, b], min_diff=3, time_limit=10)).decks[0]["cards"]
    assert len(set(b) - set(a)) >= 3
    assert len(set(c) - set(a)) >= 3 and len(set(c) - set(b)) >= 3


def test_no_more_alternatives_is_explained():
    a = solve(PLAYER, GAME, EVALS, SolveRequest(time_limit=10)).decks[0]["cards"]
    # Con 7 cartas obligatorias solo puede cambiar 1: pedir 3 distintas es imposible.
    res = solve(PLAYER, GAME, EVALS, SolveRequest(locked=a[:7], exclude_decks=[a], min_diff=3, time_limit=10))
    assert not res.ok
    assert any("alternativas" in n for n in res.notes)


def test_archetypes_only_use_their_own_win_conditions():
    from crdeck.catalog import norm
    from crdeck.solver import archetype_wincons
    for key, arch in GAME.archetypes.items():
        res = solve(PLAYER, GAME, EVALS, SolveRequest(archetypes=[key], time_limit=10))
        if not res.ok:
            continue
        allowed = {norm(c) for c in archetype_wincons(arch)}
        wincons = [c for c in res.decks[0]["cards"] if "win_condition" in PLAYER.cards[c].roles]
        assert all(norm(c) in allowed for c in wincons), (key, wincons)


def test_locked_card_overrides_archetype_win_conditions():
    res = solve(PLAYER, GAME, EVALS, SolveRequest(archetypes=["graveyard"], locked=["Hog Rider"], time_limit=10))
    assert res.ok and {"Graveyard", "Hog Rider"} <= set(res.decks[0]["cards"])


def test_rank_archetypes_sorted_and_complete():
    from crdeck.ranking import rank_archetypes
    best, rows = rank_archetypes(PLAYER, GAME, EVALS, time_limit=10)
    assert best is not None
    assert {r.key for r in rows} == set(GAME.archetypes)
    scores = [r.score for r in rows if r.ok]
    assert scores == sorted(scores, reverse=True)
    assert all(r.ok for r in rows[:len(scores)])   # los imposibles van al final


def test_lock_and_ban():
    res = solve(PLAYER, GAME, EVALS, SolveRequest(locked=["Golem"], banned=["Hog Rider"], time_limit=10))
    assert res.ok
    assert "Golem" in res.decks[0]["cards"] and "Hog Rider" not in res.decks[0]["cards"]


def test_war_decks_do_not_repeat_cards():
    res = solve(PLAYER, GAME, EVALS, SolveRequest(n_decks=4, war_unique=True, time_limit=10))
    assert res.ok
    all_cards = [c for d in res.decks for c in d["cards"]]
    assert len(all_cards) == 32 == len(set(all_cards))
    for d in res.decks:
        check_rules(d)


def test_level_normalization():
    # Una legendaria con level=6 y maxLevel=8 está a nivel 14 en la escala de 16.
    raw = {"tag": "#X", "name": "t", "cards": [
        {"name": "Knight", "level": 16, "maxLevel": 16},
        {"name": "Miner", "level": 6, "maxLevel": 8, "rarity": "legendary"},
    ]}
    from crdeck.collection import parse_player
    p = parse_player(raw, GAME)
    assert p.cards["Miner"].level == 14


# ---------------------------------------------------------------- mensajes de la API
import httpx
import pytest

from crdeck import api


def _fake_get(status, body):
    def get(url, headers=None, timeout=None):
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))
    return get


def test_placeholder_key_is_detected():
    with pytest.raises(api.ApiError, match="texto de ejemplo"):
        api.fetch_player("#99C990LLY", api_key="pega_aqui_tu_clave", use_cache=False)


def test_403_invalid_ip_shows_ip(monkeypatch):
    monkeypatch.setattr(api.httpx, "get", _fake_get(403, {
        "reason": "accessDenied.invalidIp",
        "message": "Invalid authorization: API key does not allow access from IP 203.0.113.7"}))
    with pytest.raises(api.ApiError, match="203.0.113.7"):
        api.fetch_player("#99C990LLY", api_key="x" * 50, use_cache=False)


def test_403_invalid_key(monkeypatch):
    monkeypatch.setattr(api.httpx, "get", _fake_get(403, {"reason": "accessDenied", "message": "Invalid authorization"}))
    with pytest.raises(api.ApiError, match="no es válida"):
        api.fetch_player("#99C990LLY", api_key="x" * 50, use_cache=False)

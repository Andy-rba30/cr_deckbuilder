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

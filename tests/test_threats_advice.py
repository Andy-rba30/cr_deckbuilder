from crdeck.advice import suggest_swaps
from crdeck.catalog import load_game_data, norm
from crdeck.comfort import apply_comfort
from crdeck.loader import load_player
from crdeck.scoring import evaluate_cards, evaluate_deck, pick_evos, rule_checks
from crdeck.solver import SolveRequest, solve
from crdeck.threats import answers, coverage

GAME = load_game_data()
PLAYER = apply_comfort(load_player(GAME, demo=True), None, GAME.rules["comfort"])
EVALS = evaluate_cards(PLAYER, GAME, 15)
ANS = answers(GAME, PLAYER)


def _eval(deck):
    return evaluate_deck(deck, pick_evos(deck, PLAYER, EVALS, 2), PLAYER, GAME, EVALS)


# ---------------------------------------------------------------- amenazas
def test_threat_file_uses_known_card_names():
    known = {norm(n) for n in GAME.cards}
    for key, t in GAME.threats["threats"].items():
        assert {"name", "need"} <= set(t), key
        unknown = [c for c in (t.get("cards") or {}) if norm(c) not in known]
        assert not unknown, (key, unknown)


def test_answers_use_overrides_over_roles():
    assert ANS["air"]["Musketeer"] == 1.0          # por rol air_defense
    assert ANS["air"]["Fire Spirit"] == 0.3        # valor exacto del archivo
    assert "Hog Rider" not in ANS["air"]


def test_deck_without_air_defense_gets_warning():
    ground = ["Hog Rider", "Valkyrie", "Knight", "Cannon", "Skeletons", "Ice Golem", "The Log", "Earthquake"]
    cov = {t["key"]: t["cov"] for t in coverage(ground, GAME, ANS)}
    assert cov["air"] < 0.5 and cov["swarm"] >= 0.8
    assert any("aéreos" in w for w in _eval(ground)["warnings"])


def test_coverage_is_part_of_the_score():
    d = _eval(PLAYER.current_deck)
    assert d["parts"]["amenazas"] > 0
    assert abs(d["score"] - sum(d["parts"].values())) < 1e-9
    assert 0 <= d["ratings"]["Cobertura"] <= 10


def test_solver_covers_air():
    d = solve(PLAYER, GAME, EVALS, SolveRequest(time_limit=10)).decks[0]
    cov = {t["key"]: t["cov"] for t in d["coverage"]}
    assert cov["air"] >= 0.8 and cov["tank"] >= 0.5


# ---------------------------------------------------------------- reemplazos
def test_swaps_respect_rules_and_improve_the_deck():
    bad = list(PLAYER.current_deck)
    bad[bad.index("Ice Spirit")] = "Giant Skeleton"     # carta peor y cara
    swaps = suggest_swaps(bad, PLAYER, GAME, EVALS)
    assert swaps and swaps[0]["gain"] > 0
    assert len({s["in"] for s in swaps}) == len(swaps)          # no repite la carta que entra
    assert len({s["out"] for s in swaps}) == len(swaps)
    base = _eval(bad)["score"]
    for s in swaps:
        new = [s["in"] if c == s["out"] else c for c in bad]
        assert all(ok for _, ok, hard in rule_checks(new, PLAYER, GAME) if hard)
        assert abs(_eval(new)["score"] - base - s["gain"]) < 1e-6


def test_swaps_skip_locked_and_banned_cards():
    bad = list(PLAYER.current_deck)
    bad[bad.index("Ice Spirit")] = "Giant Skeleton"
    swaps = suggest_swaps(bad, PLAYER, GAME, EVALS, locked=["Giant Skeleton"], banned=["Skeletons"])
    assert all(s["out"] != "Giant Skeleton" and s["in"] != "Skeletons" for s in swaps)


# ---------------------------------------------------------------- complementos (needs.yaml)
def test_needs_file_uses_known_card_names():
    known = {norm(n) for n in GAME.cards}
    for key, n in GAME.needs["needs"].items():
        for field in ("cards", "providers"):
            unknown = [c for c in (n.get(field) or {}) if norm(c) not in known]
            assert not unknown, (key, field, unknown)
        assert "{p}" in n["good"] and "{c}" in n["good"] and "{c}" in n["bad"], key


def test_earthquake_covers_hog_rider_buildings():
    hog = ["Hog Rider", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "Fireball", "The Log"]
    with_eq = hog[:-1] + ["Earthquake"]
    a, b = _eval(hog), _eval(with_eq)
    cov = lambda d: next(i["cov"] for i in d["complements"] if i["card"] == "Hog Rider" and i["key"] == "clear_buildings")
    assert cov(b) > cov(a)
    assert any("Terremoto" in t and "Montapuercos" in t for t, *_ in b["works"])
    assert b["parts"]["complementos"] > a["parts"]["complementos"]


def test_uncovered_need_is_explained():
    balloon = ["Balloon", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "The Log", "Zap"]
    d = _eval(balloon)
    assert any("antiaéreas" in t and "Globo" in t for t, *_ in d["missing"])


def test_locked_balloon_gets_support():
    d = solve(PLAYER, GAME, EVALS, SolveRequest(locked=["Balloon"], time_limit=10)).decks[0]
    cov = {i["key"]: i["cov"] for i in d["complements"] if i["card"] == "Balloon"}
    assert cov["clear_air_defense"] >= 0.5      # algo despeja las antiaéreas que paran al Globo


def test_win_condition_count_is_only_a_recommendation():
    three = ["Hog Rider", "Goblin Barrel", "Miner"]
    res = solve(PLAYER, GAME, EVALS, SolveRequest(locked=three, time_limit=10))
    assert res.ok                                       # antes era imposible (máx. 2)
    d = res.decks[0]
    assert d["parts"]["recomendaciones"] < 0
    assert any(w.startswith("Recomendación") for w in d["warnings"])
    checks = rule_checks(d["cards"], PLAYER, GAME)
    assert any(not ok and not hard for _, ok, hard in checks)

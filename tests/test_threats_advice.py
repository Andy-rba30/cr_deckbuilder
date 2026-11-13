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
        assert all(ok for _, ok in rule_checks(new, PLAYER, GAME))
        assert abs(_eval(new)["score"] - base - s["gain"]) < 1e-6


def test_swaps_skip_locked_and_banned_cards():
    bad = list(PLAYER.current_deck)
    bad[bad.index("Ice Spirit")] = "Giant Skeleton"
    swaps = suggest_swaps(bad, PLAYER, GAME, EVALS, locked=["Giant Skeleton"], banned=["Skeletons"])
    assert all(s["out"] != "Giant Skeleton" and s["in"] != "Skeletons" for s in swaps)

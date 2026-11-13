import copy

from crdeck.catalog import load_game_data
from crdeck.comfort import apply_comfort, familiarity
from crdeck.loader import load_player
from crdeck.scoring import evaluate_cards, evaluate_deck, pick_evos
from crdeck.solver import SolveRequest, solve

GAME = load_game_data()
CFG = GAME.rules["comfort"]
BAIT = ["Goblin Barrel", "Princess", "Goblin Gang", "Knight", "Inferno Tower", "Rocket", "The Log", "Ice Spirit"]
HOG = ["Hog Rider", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "Fireball", "The Log"]


def _battle(my_cards, tag="#DEMO", selection="collection", teammates=()):
    team = [{"tag": tag, "cards": [{"name": c} for c in my_cards]}]
    team += [{"tag": t, "cards": [{"name": "Golem"}] * 8} for t in teammates]
    return {"deckSelection": selection, "team": team, "opponent": [{"tag": "#X", "cards": [{"name": "Zap"}] * 8}]}


def test_familiarity_counts_only_your_chosen_decks():
    log = [_battle(HOG), _battle(HOG), _battle(BAIT),
           _battle(BAIT, selection="draft"),                 # mazo que no eliges: no cuenta
           _battle(BAIT, teammates=["#AMIGO"])]              # 2v2: cuenta tu mazo, no el de tu compañero
    fam, n = familiarity("#demo", log, current_deck=[])
    assert n == 4
    assert fam["Hog Rider"] == 0.5 and fam["Goblin Barrel"] == 0.5
    assert fam["The Log"] == 1.0                             # está en los dos mazos
    assert "Golem" not in fam and "Zap" not in fam


def test_current_deck_counts_even_without_history():
    fam, n = familiarity("#DEMO", [], current_deck=BAIT, current_floor=0.6)
    assert n == 0 and all(fam[c] == 0.6 for c in BAIT)
    fam, _ = familiarity("#DEMO", [_battle(HOG)], current_deck=BAIT, current_floor=0.6)
    assert fam["The Log"] == 1.0 and fam["Goblin Barrel"] == 0.6 and fam["Hog Rider"] == 1.0


def test_demo_reads_current_deck():
    p = apply_comfort(load_player(GAME, demo=True), None, CFG)
    assert p.current_deck == BAIT
    assert p.comfort_source == "tu mazo actual"


def test_bonus_goes_into_value_and_score_breakdown():
    p = apply_comfort(load_player(GAME, demo=True), None, CFG)
    base = evaluate_cards(p, GAME, 15, 1.0, 0.0)
    ev = evaluate_cards(p, GAME, 15, 1.0, 0.2)
    assert abs(ev["Goblin Barrel"].value - base["Goblin Barrel"].value - 0.2 * 0.6) < 1e-9
    assert ev["Hog Rider"].comfort == 0.0
    d = evaluate_deck(BAIT, pick_evos(BAIT, p, ev, 2), p, GAME, ev)
    assert abs(d["parts"]["comodidad"] - 8 * 0.2 * 0.6) < 1e-9
    assert abs(d["score"] - sum(d["parts"].values())) < 1e-9


def test_higher_bonus_keeps_more_of_your_deck():
    p = apply_comfort(load_player(GAME, demo=True), None, CFG)
    kept = []
    for w in (0.0, 0.3):
        deck = solve(p, GAME, evaluate_cards(p, GAME, 15, 1.0, w), SolveRequest(time_limit=10)).decks[0]["cards"]
        kept.append(len(set(deck) & set(BAIT)))
    assert kept[1] > kept[0] and kept[1] >= 6


def test_without_bonus_nothing_changes():
    p = load_player(GAME, demo=True)
    p2 = apply_comfort(copy.deepcopy(p), None, CFG)
    a, b = evaluate_cards(p, GAME, 15), evaluate_cards(p2, GAME, 15, 1.0, 0.0)
    assert all(a[n].value == b[n].value for n in a)

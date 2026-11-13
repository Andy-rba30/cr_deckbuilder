"""Motor v4: lector de la wiki, fichas de puntos y reglas sobre atributos."""
import httpx
import pytest

from crdeck.attributes import RuleError, apply_attributes, build_fichas, compile_expr, evaluate, load_rules
from crdeck.catalog import load_game_data, norm
from crdeck.collection import attach_catalog, parse_player
from crdeck.loader import load_player
from crdeck.scoring import evaluate_cards
from crdeck.solver import SolveRequest, solve
from crdeck.wiki import fetch_all, load_stats, parse_page

GAME = load_game_data()
STATS = load_stats()
RULES = load_rules()
V4 = apply_attributes(GAME, STATS, RULES)

# Página inventada con la misma estructura de tablas que usa la wiki.
PAGE = """
<p>Short.</p>
<p>The Test Rider is a Rare card. It spawns a fast, single-target, building-targeting, melee troop. It stuns
enemies when it lands. He appears as a man with a shield.</p>
<table class="wikitable" id="unit-attributes-table"><tr><th>Cost</th><th>Hit Speed</th><th>Speed</th>
<th>Range</th><th>Target</th><th>Count</th><th>Transport</th><th>Type</th><th>Rarity</th></tr>
<tr><td>4</td><td>1.6 sec</td><td>Very Fast (120)</td><td>Melee: Short (0.8)</td><td>Buildings</td><td>x1</td>
<td>Ground</td><td>Troop</td><td>Rare</td></tr></table>
<table class="wikitable" id="unit-statistics-table"><tr><th>Level</th><th>Hitpoints</th><th>Damage</th>
<th>Damage Per Second</th></tr><tr><td>10</td><td>1,543</td><td>288</td><td>180</td></tr>
<tr><td>11</td><td>1,697</td><td>317</td><td>198</td></tr></table>
"""


def test_parse_page_reads_attributes_stats_and_abilities():
    p = parse_page(PAGE)
    assert p["attributes"]["Cost"] == 4 and p["attributes"]["Speed"] == 120 and p["attributes"]["Range"] == 0.8
    assert p["attributes"]["Target"] == "Buildings"
    assert p["stats"] == {"Hitpoints": 1697, "Damage": 317, "Damage Per Second": 198}   # fila del nivel 11
    assert "stun" in p["abilities"] and "shield" not in p["abilities"]   # "shield" está en su aspecto, no cuenta


def test_fetch_all_reads_card_evolution_and_hero():
    pages = {"Test Rider": PAGE, "Test Rider/Evolution": PAGE.replace("stuns", "heals")}

    def handler(request):
        title = request.url.params["page"]
        if title not in pages:
            return httpx.Response(200, json={"error": {"code": "missingtitle"}})
        return httpx.Response(200, json={"parse": {"title": title, "text": pages[title]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        data = fetch_all(["Test Rider", "Nope"], delay=0, client=client)
    assert data["missing"] == ["Nope"]
    card = data["cards"]["Test Rider"]
    assert "evolution" in card and "hero" not in card and "heal" in card["evolution"]["abilities"]


def test_rules_reject_code():
    for bad in ["__import__('os')", "open('x')", "().__class__", "c.tanque"]:
        with pytest.raises((RuleError, SyntaxError)):
            compile_expr(bad)
    assert evaluate(compile_expr("clip(escala(5, 0, 10) / 10)"), {}) == 0.5


# ---------------------------------------------------------------- fichas con los datos de la wiki
@pytest.mark.skipif(not STATS.get("cards"), reason="sin data/card_stats.json")
def test_fichas_make_sense():
    f = build_fichas(STATS, GAME, RULES)
    assert f["golem"].points["tanque"] > f["knight"].points["tanque"] > f["skeletons"].points["tanque"]
    assert f["hogrider"].variables["ataca_edificios"] == 1 and f["hogrider"].points["velocidad"] >= 9
    assert f["zap"].points["control"] == 10 and f["earthquake"].points["derribo"] >= 9
    assert f["musketeer"].points["antiaereo"] > 0 and f["valkyrie"].points["antiaereo"] == 0
    assert f["knight"].evolution["tanque"] > f["knight"].points["tanque"]     # la evo reduce el daño recibido


@pytest.mark.skipif(not STATS.get("cards"), reason="sin data/card_stats.json")
def test_real_breakpoints_from_stats():
    k = {(i.attacker, i.target): i.k for i in V4.interactions}
    assert k[("Fireball", "Musketeer")] == 1        # la Bola de fuego mata a la Mosquetera con +1 nivel
    assert k[("The Log", "Princess")] <= 0          # el Tronco mata a la Princesa a igual nivel
    assert all(i.verified for i in V4.interactions)


@pytest.mark.skipif(not STATS.get("cards"), reason="sin data/card_stats.json")
def test_v4_rules_come_from_points():
    needs = V4.needs["needs"]
    assert needs["clear_buildings"]["cards"]["Hog Rider"] > 0.8
    assert needs["clear_buildings"]["providers"]["Earthquake"] > 0.8
    assert "Hog Rider" not in needs["clear_buildings"]["providers"]
    assert V4.threats["threats"]["air"]["cards"].get("Musketeer", 0) > 0.5
    assert any(s.source == "atributos" and {s.a, s.b} == {"Golem", "Lava Hound"} and s.weight < 0 for s in V4.synergies)


@pytest.mark.skipif(not STATS.get("cards"), reason="sin data/card_stats.json")
def test_new_cards_get_roles_and_can_be_used():
    assert norm("Ronin") in V4.cards and V4.info("Minion Giant").roles >= {"win_condition"}
    raw = {"tag": "#X", "name": "t", "cards": [
        {"name": n, "level": 14, "maxLevel": 16, "id": i} for i, n in enumerate(
            ["Minion Giant", "Ronin", "Berserker", "Musketeer", "Archers", "The Log", "Fireball", "Cannon", "Skeletons",
             "Ice Spirit", "Knight", "Zap"])]}
    player = attach_catalog(parse_player(raw, GAME), V4)
    assert player.cards["Minion Giant"].roles >= {"win_condition"}
    res = solve(player, V4, evaluate_cards(player, V4, 14), SolveRequest(locked=["Minion Giant"], time_limit=10))
    assert res.ok and "Minion Giant" in res.decks[0]["cards"] and res.decks[0]["points"]


@pytest.mark.skipif(not STATS.get("cards"), reason="sin data/card_stats.json")
def test_both_engines_work_on_the_demo():
    player = load_player(GAME, demo=True)
    for game in (GAME, V4):
        attach_catalog(player, game)
        d = solve(player, game, evaluate_cards(player, game, 15), SolveRequest(time_limit=10)).decks[0]
        assert len(d["cards"]) == 8
        assert bool(d["points"]) == (game is V4)

"""Pruebas de la interfaz con el simulador de Streamlit (no abre navegador)."""
import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _app():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _html(at):
    return " ".join(h.proto.body for h in at.get("html"))


def test_results_survive_changing_another_control():
    at = _app()
    at.button(key="b_opt").click().run()
    assert "Mejor mazo" in _html(at)

    # Mover un control vuelve a ejecutar el script: el mazo debe seguir ahí.
    at.number_input(key="alt_opt").set_value(1).run()
    assert not at.exception
    assert "Mejor mazo" in _html(at)
    assert any("otros ajustes" in i.value for i in at.info)


def test_archetype_ranking_is_shown():
    at = _app()
    at.button(key="b_rank").click().run()
    assert not at.exception
    assert _html(at).count("crd-rank") >= 5     # una fila visual por arquetipo


def test_decks_are_drawn_as_card_grids():
    at = _app()
    at.button(key="b_opt").click().run()
    html = _html(at)
    assert "crd-deck" in html and html.count('class="crd-card') >= 8 and "Copiar al juego" in html


def test_builder_complete_and_toggle_cards():
    at = _app()
    complete = next(b for b in at.button if b.label.startswith("✨"))
    complete.click().run()
    assert not at.exception
    deck = at.session_state["builder"]
    assert len(deck) == 8
    at.button(key=f"add_{deck[0]}").click().run()          # quitar
    assert len(at.session_state["builder"]) == 7
    other = next(n for n in ["Knight", "Bats", "Zap", "Arrows"] if n not in deck)
    at.button(key=f"add_{other}").click().run()            # añadir
    assert at.session_state["builder"][-1] == other and not at.exception


def test_current_deck_and_comfort_controls():
    at = _app()
    assert any("Tu mazo actual" in e.label for e in at.expander)
    assert any("cartas que ya juegas" in s.label.lower() for s in at.slider)
    at.button(key="b_opt").click().run()
    assert "vs. tu mazo actual" in _html(at)
    load = next(b for b in at.button if b.label.startswith("📌"))
    load.click().run()
    assert at.session_state["builder"] == ["Goblin Barrel", "Princess", "Goblin Gang", "Knight", "Inferno Tower",
                                           "Rocket", "The Log", "Ice Spirit"]
    assert "crd-fam" in _html(at) and not at.exception

"""Pruebas de la interfaz con el simulador de Streamlit (no abre navegador)."""
import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _app():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _subheaders(at):
    return [s.value for s in at.subheader]


def test_results_survive_changing_another_control():
    at = _app()
    at.button(key="b_opt").click().run()
    assert "Mejor mazo" in _subheaders(at)

    # Mover un control vuelve a ejecutar el script: el mazo debe seguir ahí.
    at.number_input(key="alt_opt").set_value(1).run()
    assert not at.exception
    assert "Mejor mazo" in _subheaders(at)
    assert any("otros ajustes" in i.value for i in at.info)


def test_archetype_ranking_is_shown():
    at = _app()
    at.button(key="b_rank").click().run()
    assert not at.exception
    assert len(at.dataframe) >= 2   # ranking + tabla de la colección

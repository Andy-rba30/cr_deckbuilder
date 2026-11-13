"""Interfaz web local:  streamlit run app.py"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from crdeck.api import ApiError
from crdeck.collection import default_reference_level, parse_player
from crdeck.deck_link import copy_link
from crdeck.loader import ENV_PATH, load_env, load_game_data, load_player
from crdeck.scoring import evaluate_cards
from crdeck.solver import SolveRequest, solve
from crdeck.upgrade import upgrade_advice

st.set_page_config(page_title="Recomendador de mazos CR", page_icon="🃏", layout="wide")
ENV_FOUND = load_env()


@st.cache_resource
def game_data():
    return load_game_data()


game = game_data()

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("1. Tu cuenta")
    source = st.radio("Origen de los datos", ["Demo", "Player Tag (API)", "Archivo JSON"], index=0)
    player = None
    try:
        if source == "Demo":
            player = load_player(game, demo=True)
        elif source == "Player Tag (API)":
            if not ENV_FOUND:
                st.warning(f"No encuentro el archivo .env. Debe estar en: {ENV_PATH}")
            tag = st.text_input("Player Tag", placeholder="#ABC123")
            if tag:
                player = load_player(game, tag=tag)
        else:
            up = st.file_uploader("Respuesta de /players/{tag} en JSON", type="json")
            if up:
                player = parse_player(json.load(up), game)
    except (ApiError, ValueError) as e:
        st.error(str(e))

    if player:
        st.success(f"{player.name} ({player.tag}) — {len(player.cards)} cartas")
        st.header("2. Ajustes")
        ref = st.slider("Nivel de referencia (rivales)", 1, player.max_level,
                        default_reference_level(player),
                        help="Nivel típico de tus rivales. Por defecto: la mediana de tus mejores cartas.")
        level_weight = st.slider("Importancia del nivel", 0.0, 2.0, 1.0, 0.1,
                                 help="0 = ignora niveles · 1 = normal · 2 = castiga mucho las cartas bajas")
        time_limit = st.slider("Tiempo máximo del solver (s)", 5, 120, 20)
        names_es = {c.es: n for n, c in sorted(player.cards.items(), key=lambda kv: kv[1].es)}
        locked = [names_es[x] for x in st.multiselect("Cartas obligatorias", list(names_es))]
        banned = [names_es[x] for x in st.multiselect("Cartas prohibidas", list(names_es))]

if not player:
    st.title("🃏 Recomendador de mazos")
    st.info("Elige el origen de los datos en la barra lateral. El modo Demo funciona sin clave de API.")
    st.stop()

evals = evaluate_cards(player, game, ref, level_weight)


def show_deck(title: str, d: dict):
    st.subheader(title)
    cols = st.columns(8)
    for col, name in zip(cols, d["cards"]):
        oc = player.cards[name]
        with col:
            img = oc.icon_evo if (name in d["evos"] and oc.icon_evo) else oc.icon
            if img:
                st.image(img, width="stretch")
            badge = " ✨EVO" if name in d["evos"] else (" 👑" if oc.champion else "")
            st.markdown(f"**{oc.es}**{badge}  \nnv {oc.level} · {oc.elixir:g}💧")
    m = st.columns(6)
    m[0].metric("Puntaje", f"{d['score']:.2f}")
    m[1].metric("Elixir medio", f"{d['avg_elixir']:.1f}")
    for i, (k, v) in enumerate(d["ratings"].items(), start=2):
        m[i].metric(k, f"{v:.1f}/10")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Sinergias activas**")
        if not d["synergies"]:
            st.caption("Ninguna")
        for a, b, w, r in d["synergies"]:
            st.markdown(f"{'🟢' if w > 0 else '🔴'} {a} + {b} ({w:+.2f}) — {r}")
        st.markdown("**Roles cubiertos**")
        st.markdown(" · ".join(f"{'✅' if ok else '❌'} {n}" for n, _, ok in d["role_checks"]))
    with c2:
        st.markdown("**Advertencias**")
        if not d["warnings"]:
            st.caption("Ninguna")
        for w in d["warnings"]:
            st.markdown(f"⚠️ {w}")
        p = d["parts"]
        st.caption(f"Desglose: cartas {p['cartas']:.2f} + evoluciones {p['evoluciones']:.2f} + "
                   f"sinergias {p['sinergias']:.2f} + roles {p['roles']:.2f}")
    link = copy_link(d["cards"], player)
    if link:
        st.markdown(f"[📋 Copiar mazo al juego]({link})")
        st.caption("Revisa en el juego que las evoluciones queden en sus espacios.")
    st.divider()


def run(req: SolveRequest, n_alternatives: int = 0, label=lambda i, d: f"Mazo {i}"):
    shown = []
    with st.spinner("Resolviendo el modelo ILP..."):
        for k in range(n_alternatives + 1):
            req.exclude_decks = shown
            res = solve(player, game, evals, req)
            for n in res.notes:
                st.warning(n)
            if not res.ok:
                break
            for i, d in enumerate(res.decks, 1):
                show_deck(label(k + i, d), d)
            shown = shown + [d["cards"] for d in res.decks]


st.title("🃏 Recomendador de mazos")
if player.unknown_cards:
    st.caption("Cartas sin metadatos (agrégalas a data/cards.yaml): " + ", ".join(player.unknown_cards))

tab_opt, tab_arch, tab_war, tab_up, tab_col = st.tabs(
    ["⭐ Óptimo", "🧩 Arquetipo", "⚔️ Guerra de clanes", "📈 Asesor de mejoras", "📚 Mi colección"])

with tab_opt:
    st.caption("El mejor mazo posible con tus cartas y niveles.")
    alts = st.number_input("Alternativas extra", 0, 5, 2, key="alt_opt")
    if st.button("Recomendar", key="b_opt", type="primary"):
        run(SolveRequest(locked=locked, banned=banned, time_limit=time_limit), alts,
            lambda i, d: "Mejor mazo" if i == 1 else f"Alternativa {i - 1}")

with tab_arch:
    keys = list(game.archetypes)
    arch = st.selectbox("Arquetipo", keys, format_func=lambda k: game.archetypes[k]["name"])
    alts = st.number_input("Alternativas extra", 0, 5, 1, key="alt_arch")
    if st.button("Armar variante", key="b_arch", type="primary"):
        run(SolveRequest(archetypes=[arch], locked=locked, banned=banned, time_limit=time_limit), alts,
            lambda i, d: f"{d['archetype']} — variante {i}")

with tab_war:
    st.caption("4 mazos sin cartas repetidas, optimizados a la vez para que ninguno quede débil.")
    opts = [None] + list(game.archetypes)
    fmt = lambda k: "Automático" if k is None else game.archetypes[k]["name"]
    wcols = st.columns(4)
    war_archs = [wcols[i].selectbox(f"Mazo {i + 1}", opts, format_func=fmt, key=f"war{i}") for i in range(4)]
    if st.button("Armar los 4 mazos", key="b_war", type="primary"):
        run(SolveRequest(n_decks=4, war_unique=True, archetypes=war_archs,
                         locked=locked, banned=banned, time_limit=time_limit),
            0, lambda i, d: f"Mazo {i}" + (f" — {d['archetype']}" if d["archetype"] else ""))

with tab_up:
    st.caption("Simula subir cada carta un nivel y mide cuánto mejora tu mejor mazo.")
    up_arch = st.selectbox("Para el modo", [None] + list(game.archetypes),
                           format_func=lambda k: "Óptimo" if k is None else game.archetypes[k]["name"])
    if st.button("Calcular", key="b_up", type="primary"):
        with st.spinner("Simulando mejoras..."):
            rows = upgrade_advice(player, game, ref, level_weight,
                                  SolveRequest(archetypes=[up_arch] if up_arch else [], locked=locked, banned=banned))
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

with tab_col:
    rows = [{
        "Carta": c.es, "Nivel": c.level, "Rareza": c.rarity, "Elixir": c.elixir,
        "Evo": "✨" if c.evo_unlocked else "", "Roles": ", ".join(sorted(c.roles)),
        "Factor nivel": round(evals[n].level_factor, 2), "Valor": round(evals[n].value, 3),
    } for n, c in player.cards.items()]
    st.dataframe(pd.DataFrame(rows).sort_values("Valor", ascending=False),
                 width="stretch", hide_index=True)

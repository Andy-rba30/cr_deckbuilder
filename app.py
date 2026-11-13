"""Interfaz web local:  streamlit run app.py"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from crdeck import ui
from crdeck.api import ApiError, fetch_battlelog
from crdeck.battles import BATTLES_PATH, crawl, load_cards_info, save_battles
from crdeck.collection import default_reference_level, parse_player
from crdeck.comfort import apply_comfort
from crdeck.deck_link import copy_link
from crdeck.loader import ENV_PATH, load_env, load_game_data, load_player
from crdeck.meta import load_battle_meta
from crdeck.ranking import ArchetypeRank, rank_archetypes
from crdeck.scoring import evaluate_cards, evaluate_deck, pick_evos
from crdeck.solver import SolveRequest, solve
from crdeck.upgrade import upgrade_advice

st.set_page_config(page_title="Recomendador de mazos CR", page_icon="🃏", layout="wide")
ENV_FOUND = load_env()
st.html(ui.CSS)


@st.cache_resource
def base_game():
    return load_game_data()


@st.cache_resource
def meta_game(mtime: float | None):
    """Catálogo con el meta de data/battles.json aplicado; se recalcula cuando cambia el archivo."""
    game, bm = load_battle_meta(base_game())
    return game, bm, load_cards_info()


BASE = base_game()
GAME_META, BM, SEEN_CARDS = meta_game(BATTLES_PATH.stat().st_mtime if BATTLES_PATH.exists() else None)
CFG_META = BASE.rules["battle_meta"]


def fecha(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


# ------------------------------------------------------------------ barra lateral
api_tag = None
with st.sidebar:
    st.header("1. Tu cuenta")
    source = st.radio("Origen de los datos", ["Demo", "Player Tag (API)", "Archivo JSON"], index=0)
    player = None
    try:
        if source == "Demo":
            player = load_player(BASE, demo=True)
        elif source == "Player Tag (API)":
            if not ENV_FOUND:
                st.warning(f"No encuentro el archivo .env. Debe estar en: {ENV_PATH}")
            tag = st.text_input("Player Tag", placeholder="#ABC123")
            if tag:
                player = load_player(BASE, tag=tag)
                api_tag = tag
        else:
            up = st.file_uploader("Respuesta de /players/{tag} en JSON", type="json")
            if up:
                player = parse_player(json.load(up), BASE)
    except (ApiError, ValueError) as e:
        st.error(str(e))

    log_err = None
    if player:   # cartas que ya juegas: tu historial (con Player Tag) y tu mazo actual
        log = None
        if api_tag:
            try:
                log = fetch_battlelog(api_tag)
            except ApiError as e:
                log_err = str(e)
        apply_comfort(player, log, BASE.rules["comfort"])

    if player:
        st.success(f"{player.name} ({player.tag}) — {len(player.cards)} cartas")
        st.header("2. Ajustes")
        ref = st.slider("Nivel de referencia (rivales)", 1, player.max_level,
                        default_reference_level(player),
                        help="Nivel típico de tus rivales. Por defecto: la mediana de tus mejores cartas.")
        level_weight = st.slider("Importancia del nivel", 0.0, 2.0, 1.0, 0.1,
                                 help="0 = ignora niveles · 1 = normal · 2 = castiga mucho las cartas bajas")
        comfort_weight = st.slider(
            "Bonus por cartas que ya juegas", 0.0, 0.5, float(BASE.rules["comfort"]["weight"]), 0.01,
            help="Suma este valor a una carta que usas en todas tus batallas (proporcional a cuánto la usas). "
                 "0 = sin bonus · 0.1 desempata · 0.3 o más se queda cerca de tu mazo actual.")
        st.caption(f"♥ {sum(f >= ui.FAMILIAR_MIN for f in player.comfort.values())} cartas que juegas seguido, "
                   f"según {player.comfort_source}." if player.comfort else "Sin datos de las cartas que juegas.")
        if log_err:
            st.caption(f"No se pudo leer tu historial: {log_err}")
        time_limit = st.slider("Tiempo máximo del solver (s)", 5, 120, 20)
        min_diff = st.slider("Cartas distintas entre alternativas", 1, 6, 3,
                             help="Cuántas cartas debe cambiar cada alternativa respecto a los mazos ya mostrados.")
        use_meta = st.toggle("Usar meta de batallas reales", value=BM is not None, disabled=BM is None,
                             help="Ajusta la fuerza de las cartas y las sinergias con batallas reales "
                                  "(pestaña 📊 Meta).")
        st.caption(f"{BM.n_battles} batallas · {fecha(BM.first)}–{fecha(BM.last)}" if BM
                   else "Sin batallas guardadas: descárgalas en la pestaña 📊 Meta.")
        names_es = {c.es: n for n, c in sorted(player.cards.items(), key=lambda kv: kv[1].es)}
        locked = [names_es[x] for x in st.multiselect("Cartas obligatorias", list(names_es))]
        banned = [names_es[x] for x in st.multiselect("Cartas prohibidas", list(names_es))]

if not player:
    st.title("🃏 Recomendador de mazos")
    st.info("Elige el origen de los datos en la barra lateral. El modo Demo funciona sin clave de API.")
    st.stop()

game = GAME_META if (use_meta and BM) else BASE
evals = evaluate_cards(player, game, ref, level_weight, comfort_weight)


# ------------------------------------------------------------------ piezas visuales
def es(name: str) -> str:
    info = BASE.info(name)
    return info.es if info else name


def any_tile(name: str, note: str = "", show_name: bool = True) -> str:
    """Ficha de cualquier carta: de tu colección si la tienes; si no, con los datos vistos en batallas."""
    if name in player.cards:
        return ui.owned_tile(name, player, evals, note=note, show_name=show_name)
    seen = SEEN_CARDS.get(name, {})
    info = BASE.info(name)
    elixir = seen.get("elixir") or (info.elixir if info else None)
    return ui.card_tile(es(name), elixir=elixir, rarity=seen.get("rarity", ""), icon=seen.get("icon"),
                        note=note or "no la tienes", show_name=show_name)


def show_deck(title: str, d: dict, subtitle: str | None = None):
    sub = subtitle if subtitle is not None else (d.get("archetype") or "")
    st.html(ui.deck_html(title, d, player, evals, copy_link(d["cards"], player), subtitle=sub))
    with st.expander("Detalles: sinergias, roles y avisos"):
        syn = [(f"{a} + {b}  {w:+.2f}", "good" if w > 0 else "bad", r) for a, b, w, r in d["synergies"]]
        st.markdown("**Sinergias activas**")
        if syn:
            st.html(ui.chips(syn))
        else:
            st.caption("Ninguna")
        st.markdown("**Roles cubiertos**")
        st.html(ui.chips([(("✓ " if ok else "✗ ") + n, "good" if ok else "bad", "") for n, _, ok in d["role_checks"]]))
        st.markdown("**Avisos**")
        if d["warnings"]:
            st.html(ui.chips([(w, "warn", "") for w in d["warnings"]]))
        else:
            st.caption("Ninguno")
        p = d["parts"]
        st.caption(f"Desglose del puntaje: cartas {p['cartas']:.2f} + cartas que ya juegas {p['comodidad']:.2f} + "
                   f"evoluciones {p['evoluciones']:.2f} + sinergias {p['sinergias']:.2f} + roles {p['roles']:.2f}")


def solve_with_alternatives(req: SolveRequest, n_alternatives: int = 0,
                            label=lambda i, d: f"Mazo {i}") -> list[tuple]:
    """Resuelve el mazo y sus alternativas. Devuelve ("note", texto) y ("deck", título, mazo) en orden."""
    items, shown = [], []
    for k in range(n_alternatives + 1):
        req.exclude_decks = shown
        res = solve(player, game, evals, req)
        items += [("note", n) for n in res.notes]
        if not res.ok:
            break
        items += [("deck", label(k + i, d), d) for i, d in enumerate(res.decks, 1)]
        shown = shown + [d["cards"] for d in res.decks]
    return items


def show_items(items: list[tuple], columns: int = 1, subtitle=None):
    for kind, *rest in items:
        if kind == "note":
            st.warning(rest[0])
    decks = [rest for kind, *rest in items if kind == "deck"]
    sub = (lambda d: None) if subtitle is None else subtitle
    if columns == 1:
        for title, d in decks:
            show_deck(title, d, sub(d))
        return
    for i in range(0, len(decks), columns):
        for col, (title, d) in zip(st.columns(columns), decks[i:i + columns]):
            with col:
                show_deck(title, d, sub(d))


def current_deck_eval() -> dict | None:
    """Tu mazo equipado, evaluado igual que las recomendaciones (para comparar)."""
    cd = player.current_deck
    if len(cd) != 8:
        return None
    evos = pick_evos(cd, player, evals, game.rules["deck"]["evo_slots"])
    return evaluate_deck(sorted(cd, key=lambda c: c not in evos), evos, player, game, evals)


def show_ranking(best: float | None, rows: list[ArchetypeRank]):
    ok = [a for a in rows if a.ok]
    if best is not None:
        st.caption(f"Óptimo libre (sin arquetipo): {best:.2f}. Elige uno abajo para ver el mazo completo.")
    top = max([a.score for a in ok] + [best or 0.0]) or 1.0
    for pos, a in enumerate(ok, 1):
        tiles = [ui.owned_tile(c, player, evals, evo=c in a.deck["evos"], show_name=False) for c in a.deck["cards"]]
        st.html(ui.rank_row(pos, a.name, a.score, (a.score - best) if best is not None else None,
                            a.deck["avg_elixir"], tiles, 100 * a.score / top))
    missing = [a for a in rows if not a.ok]
    if missing:
        st.markdown("**No disponibles con tus cartas**")
        st.html(ui.chips([(a.name, "bad", a.note) for a in missing]))


# ------------------------------------------------------------------ resultados guardados
# Streamlit vuelve a ejecutar todo el script con cada clic o cambio de un control.
# Los resultados se guardan en session_state para que no desaparezcan al tocar otro ajuste.
results: dict = st.session_state.setdefault("results", {})
for k in [k for k, r in results.items() if r["ctx"]["tag"] != player.tag]:
    del results[k]   # eran de otro jugador: sus cartas ya no aplican


def context(**params) -> dict:
    """Ajustes con los que se calcula un resultado; si cambian, el resultado queda desactualizado."""
    return {"tag": player.tag, "ref": ref, "level_weight": level_weight, "locked": tuple(locked),
            "banned": tuple(banned), "meta": (bool(use_meta and BM), BM.last if BM else None),
            "comfort": comfort_weight, **params}


def saved(key: str, ctx: dict) -> dict | None:
    r = results.get(key)
    if r and r["ctx"] != ctx:
        st.info("Estos resultados se calcularon con otros ajustes. Pulsa el botón para actualizarlos.")
    return r


# ------------------------------------------------------------------ páginas
st.title("🃏 Recomendador de mazos")
if player.unknown_cards:
    st.caption("Cartas sin metadatos (agrégalas a data/cards.yaml): " + ", ".join(player.unknown_cards))

tab_opt, tab_arch, tab_war, tab_build, tab_up, tab_meta, tab_col = st.tabs(
    ["⭐ Óptimo", "🧩 Arquetipos", "⚔️ Guerra de clanes", "🛠️ Creador", "📈 Mejoras", "📊 Meta", "📚 Colección"])

with tab_opt:
    st.caption("El mejor mazo posible con tus cartas y niveles.")
    current = current_deck_eval()
    if current:
        with st.expander(f"📌 Tu mazo actual · puntaje {current['score']:.2f} (para comparar)"):
            st.html(ui.deck_html("Tu mazo actual", current, player, evals, copy_link(current["cards"], player)))
    alts = st.number_input("Alternativas extra", 0, 5, 2, key="alt_opt")
    ctx = context(alts=alts, min_diff=min_diff)
    if st.button("Recomendar", key="b_opt", type="primary"):
        with st.spinner("Resolviendo el modelo ILP..."):
            results["opt"] = {"ctx": ctx, "items": solve_with_alternatives(
                SolveRequest(locked=locked, banned=banned, min_diff=min_diff, time_limit=time_limit), alts,
                lambda i, d: "Mejor mazo" if i == 1 else f"Alternativa {i - 1}")}
    if r := saved("opt", ctx):
        show_items(r["items"], subtitle=(lambda d: f"{d['score'] - current['score']:+.2f} vs. tu mazo actual")
                   if current else None)

with tab_arch:
    st.markdown("**¿Qué arquetipo te conviene?**")
    st.caption("Arma la mejor variante de cada arquetipo con tus cartas y los ordena por puntaje.")
    ctx = context()
    if st.button("Comparar arquetipos", key="b_rank"):
        with st.spinner("Armando todos los arquetipos..."):
            best, rows = rank_archetypes(player, game, evals, locked, banned, time_limit)
        results["rank"] = {"ctx": ctx, "best": best, "rows": rows}
    if r := saved("rank", ctx):
        show_ranking(r["best"], r["rows"])
    st.divider()

    keys = list(game.archetypes)
    arch = st.selectbox("Arquetipo", keys, format_func=lambda k: game.archetypes[k]["name"])
    alts = st.number_input("Alternativas extra", 0, 5, 1, key="alt_arch")
    ctx = context(arch=arch, alts=alts, min_diff=min_diff)
    if st.button("Armar variante", key="b_arch", type="primary"):
        with st.spinner("Resolviendo el modelo ILP..."):
            results["arch"] = {"ctx": ctx, "items": solve_with_alternatives(
                SolveRequest(archetypes=[arch], locked=locked, banned=banned, min_diff=min_diff,
                             time_limit=time_limit), alts,
                lambda i, d: f"{d['archetype']} — variante {i}")}
    if r := saved("arch", ctx):
        show_items(r["items"])

with tab_war:
    st.caption("4 mazos sin cartas repetidas, optimizados a la vez para que ninguno quede débil.")
    opts = [None] + list(game.archetypes)
    fmt = lambda k: "Automático" if k is None else game.archetypes[k]["name"]
    wcols = st.columns(4)
    war_archs = [wcols[i].selectbox(f"Mazo {i + 1}", opts, format_func=fmt, key=f"war{i}") for i in range(4)]
    ctx = context(archs=tuple(war_archs))
    if st.button("Armar los 4 mazos", key="b_war", type="primary"):
        with st.spinner("Resolviendo el modelo ILP (puede tardar hasta el tiempo máximo)..."):
            results["war"] = {"ctx": ctx, "items": solve_with_alternatives(
                SolveRequest(n_decks=4, war_unique=True, archetypes=war_archs,
                             locked=locked, banned=banned, time_limit=time_limit),
                0, lambda i, d: f"Mazo {i}")}
    if r := saved("war", ctx):
        show_items(r["items"], columns=2)

# ------------------------------------------------------------------ creador manual
EVO_SLOTS = BASE.rules["deck"]["evo_slots"]


def builder_order(cards: list[str]) -> tuple[list[str], list[str]]:
    """Elige las evoluciones con más bonus y las pone primero (ocupan los primeros espacios)."""
    evos = pick_evos(cards, player, evals, EVO_SLOTS)
    return sorted(cards, key=lambda c: (c not in evos, cards.index(c))), evos


def rule_checks(cards: list[str]) -> list[tuple[str, str, str]]:
    rules = game.rules["deck"]
    out = []
    for role, lim in rules["role_limits"].items():
        n = sum(role in player.cards[c].roles for c in cards)
        ok = lim.get("min", 0) <= n <= lim.get("max", 99)
        rng = f"{lim.get('min', 0)}–{lim['max']}" if "max" in lim else f"≥{lim['min']}"
        out.append((f"{'✓' if ok else '✗'} {role.replace('_', ' ')}: {n} ({rng})", "good" if ok else "bad", ""))
    n_sp = sum(bool(player.cards[c].roles & set(rules["spell_roles"])) for c in cards)
    ok = rules["min_spells"] <= n_sp <= rules["max_spells"]
    out.append((f"{'✓' if ok else '✗'} hechizos: {n_sp} ({rules['min_spells']}–{rules['max_spells']})",
                "good" if ok else "bad", ""))
    lo, hi = rules["avg_elixir"]
    avg = sum(player.cards[c].elixir for c in cards) / len(cards)
    ok = lo <= avg <= hi
    out.append((f"{'✓' if ok else '✗'} elixir {avg:.1f} ({lo}–{hi})", "good" if ok else "bad", ""))
    return out


def builder_add(name: str):
    sel = st.session_state.get("builder", [])
    if name in sel:
        st.session_state.builder = [c for c in sel if c != name]
    elif len(sel) < 8:
        st.session_state.builder = sel + [name]


def builder_complete():
    sel = st.session_state.get("builder", [])
    res = solve(player, game, evals, SolveRequest(locked=sel + locked, banned=banned, time_limit=time_limit))
    if res.ok:
        st.session_state.builder = res.decks[0]["cards"]
    else:
        st.session_state.builder_msg = " ".join(res.notes)


with tab_build:
    st.caption("Arma tu propio mazo: pulsa ＋ en las cartas de abajo y la app lo evalúa al momento. "
               "**✨ Completar** rellena los huecos con lo mejor para esas cartas.")
    if "builder" in st.session_state:   # quita cartas que este jugador no tiene
        st.session_state.builder = [c for c in st.session_state.builder if c in player.cards][:8]
    sel = st.session_state.get("builder", [])
    if msg := st.session_state.pop("builder_msg", None):
        st.warning(msg)

    if sel:
        order, evos = builder_order(sel)
        d = evaluate_deck(order, evos, player, game, evals)
        st.html(ui.deck_html("Tu mazo", d, player, evals, copy_link(order, player) if len(sel) == 8 else None,
                             subtitle=f"{len(sel)}/8 cartas", empty_slots=8 - len(sel)))
        st.html(ui.chips(rule_checks(sel)))
    else:
        st.html('<div class="crd-root"><div class="crd-deck"><div class="crd-left"><div class="crd-grid">'
                + "".join(ui.empty_tile() for _ in range(8)) + "</div></div>"
                '<div class="crd-right"><div class="crd-sub">Elige cartas abajo o pulsa ✨ Completar '
                "para empezar desde el mejor mazo.</div></div></div></div>")

    b0, b1, b2, b3 = st.columns(4)
    b0.button("📌 Cargar mi mazo actual", on_click=lambda: st.session_state.update(builder=list(player.current_deck)),
              disabled=len(player.current_deck) != 8, width="stretch")
    b1.button("✨ Completar mazo", on_click=builder_complete, disabled=len(sel) >= 8, width="stretch")
    suggest = b2.button("💡 Sugerir 3 mazos", width="stretch")
    b3.button("🗑️ Vaciar", on_click=lambda: st.session_state.update(builder=[]), disabled=not sel,
              width="stretch")
    ctx = context(builder=tuple(sorted(sel)), min_diff=min_diff)
    if suggest:
        with st.spinner("Buscando mazos..."):
            results["build"] = {"ctx": ctx, "items": solve_with_alternatives(
                SolveRequest(locked=sel + locked, banned=banned, min_diff=min_diff, time_limit=time_limit), 2,
                lambda i, d: f"Sugerencia {i}")}
    if r := saved("build", ctx):
        show_items(r["items"])

    st.markdown("#### Tus cartas")
    f1, f2 = st.columns([2, 1])
    q = f1.text_input("Buscar carta", placeholder="Montapuercos, hechizo...", key="b_q").strip().lower()
    order_by = f2.selectbox("Ordenar por", ["Valor", "Elixir", "Nivel", "Nombre"], key="b_sort")
    keyf = {"Valor": lambda n: -evals[n].value, "Elixir": lambda n: player.cards[n].elixir,
            "Nivel": lambda n: -player.cards[n].level, "Nombre": lambda n: player.cards[n].es}[order_by]
    pool = sorted((n for n in player.cards if not q or q in player.cards[n].es.lower() or q in n.lower()
                   or any(q in r for r in player.cards[n].roles)), key=keyf)
    per_row = 8
    for i in range(0, len(pool), per_row):
        for col, n in zip(st.columns(per_row), pool[i:i + per_row]):
            with col:
                st.html(ui.owned_tile(n, player, evals, evo=n in sel and player.cards[n].evo_unlocked,
                                      note=f"valor {evals[n].value:.2f}"))
                st.button("✕ Quitar" if n in sel else "＋ Añadir", key=f"add_{n}", on_click=builder_add, args=(n,),
                          disabled=n not in sel and len(sel) >= 8, width="stretch")

# ------------------------------------------------------------------ mejoras
with tab_up:
    st.caption("Simula subir cada carta un nivel y mide cuánto mejora tu mejor mazo.")
    up_arch = st.selectbox("Para el modo", [None] + list(game.archetypes),
                           format_func=lambda k: "Óptimo" if k is None else game.archetypes[k]["name"])
    ctx = context(arch=up_arch)
    if st.button("Calcular", key="b_up", type="primary"):
        with st.spinner("Simulando mejoras..."):
            rows = upgrade_advice(player, game, ref, level_weight,
                                  SolveRequest(archetypes=[up_arch] if up_arch else [], locked=locked, banned=banned),
                                  comfort_weight=comfort_weight)
        results["up"] = {"ctx": ctx, "rows": rows}
    if r := saved("up", ctx):
        rows = r["rows"]
        if not rows:
            st.caption("Sin resultados.")
        else:
            st.html(ui.pool_html([ui.owned_tile(x["nombre_api"], player, evals,
                                                note=f"nv {x['nivel_actual']}→{x['nivel_actual'] + 1}: "
                                                     f"{x['ganancia']:+.3f}") for x in rows]))
            with st.expander("Tabla"):
                st.dataframe(pd.DataFrame(rows).drop(columns=["nombre_api"]), width="stretch", hide_index=True)

# ------------------------------------------------------------------ meta de batallas reales
with tab_meta:
    st.caption("Fuerza de las cartas y sinergias calculadas con batallas reales de jugadores de tu nivel: "
               "se descarga tu historial, el de tus rivales, el de los rivales de ellos, etc.")
    if msg := st.session_state.pop("meta_msg", None):
        st.success(msg)
    if api_tag:
        c1, c2 = st.columns([3, 1])
        n_players = c1.slider("Jugadores a revisar", 20, 300, 100, 10,
                              help="1 petición a la API por jugador; cada historial trae unas 25 batallas.")
        c2.write("")
        if c2.button("⬇️ Descargar batallas", key="b_meta", type="primary", width="stretch"):
            bar = st.progress(0.0, text="Descargando historiales...")
            try:
                battles, info = crawl([api_tag], n_players, CFG_META["battle_types"], progress=lambda i, n, nb: (
                    bar.progress(min(1.0, i / n), text=f"{i}/{n} jugadores · {nb} batallas")))
                total = save_battles(battles, max_age_days=CFG_META["max_age_days"], cards_info=info["cards"])
                st.session_state.meta_msg = (f"Listo: {len(battles)} batallas descargadas "
                                             f"({info['errors']} jugadores con error). Total guardado: {total}.")
                st.rerun()
            except ApiError as e:
                st.error(str(e))
    else:
        st.info("Para descargar batallas elige **Player Tag (API)** en la barra lateral, "
                "o usa la consola: `python cli.py --tag \"#TU_TAG\" --mode meta`.")

    if BM is None:
        st.caption(f"Aún no hay batallas guardadas (o tienen más de {CFG_META['max_age_days']} días).")
    else:
        if not use_meta:
            st.warning("El meta de batallas está desactivado en la barra lateral: esto es solo informativo.")
        st.html(ui.stats_row([
            (f"{BM.n_battles}", "batallas analizadas"), (f"{BM.n_players}", "jugadores"),
            (f"{fecha(BM.first)} – {fecha(BM.last)}", "período"),
            (f"{BM.level_win_gain * 100:+.1f} pts", "de victoria por 1 nivel medio más"),
        ]))
        detail = GAME_META.meta_detail
        st.markdown("#### Cartas más fuertes según las batallas")
        st.caption("Solo cartas con suficientes partidas (los datos pesan al menos un 30%).")
        top = sorted((n for n in detail if detail[n]["peso_datos"] >= 0.3), key=lambda n: -detail[n]["datos"])[:24]
        st.html(ui.pool_html([any_tile(n, note=f"uso {BM.cards[n].usage:.0%} · {BM.cards[n].win_rate:.0%} vic.")
                              for n in top]))

        def combo(p):
            return ui.combo_html(any_tile(p.a, show_name=False), any_tile(p.b, show_name=False),
                                 f"{es(p.a)} + {es(p.b)}",
                                 f"{p.lift:.1f}× lo esperado · {p.together} mazos · peso {p.weight:+.2f}")

        pos = [p for p in BM.pairs if p.weight > 0][:12]
        neg = [p for p in BM.pairs if p.weight < 0][:8]
        for title, group in [("Combos que más se juegan juntos", pos), ("Casi nunca van juntas", neg)]:
            st.markdown(f"#### {title}")
            if group:
                st.html(ui.combos_html([combo(p) for p in group]))
            else:
                st.caption("Ninguno todavía.")
        with st.expander("Tabla completa de cartas"):
            st.dataframe(pd.DataFrame([{
                "Carta": es(n), "Partidas": s.games, "Uso %": 100 * s.usage, "Win rate %": 100 * s.win_rate,
                "Fuerza": s.strength, "Meta catálogo": detail[n]["catalogo"], "Meta final": detail[n]["final"],
                "Peso de los datos %": 100 * detail[n]["peso_datos"],
            } for n, s in BM.cards.items()]).sort_values("Meta final", ascending=False), width="stretch",
                hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.2f") for k in
                                                ["Uso %", "Win rate %", "Fuerza", "Meta catálogo", "Meta final",
                                                 "Peso de los datos %"]})

# ------------------------------------------------------------------ colección
with tab_col:
    f1, f2, f3 = st.columns([2, 2, 1])
    q = f1.text_input("Buscar", placeholder="nombre o rol (splash, building...)", key="c_q").strip().lower()
    rar = f2.multiselect("Rareza", sorted({c.rarity for c in player.cards.values()}), key="c_rar")
    order_by = f3.selectbox("Ordenar por", ["Valor", "Nivel", "Elixir", "Nombre", "Más jugadas"], key="c_sort")
    keyf = {"Valor": lambda n: -evals[n].value, "Elixir": lambda n: player.cards[n].elixir,
            "Nivel": lambda n: -player.cards[n].level, "Nombre": lambda n: player.cards[n].es,
            "Más jugadas": lambda n: -player.comfort.get(n, 0.0)}[order_by]
    names = sorted((n for n, c in player.cards.items()
                    if (not q or q in c.es.lower() or q in n.lower() or any(q in r for r in c.roles))
                    and (not rar or c.rarity in rar)), key=keyf)
    st.caption(f"{len(names)} cartas · nivel coloreado: verde = a tu nivel de referencia ({ref}) o más, "
               "ámbar = 1 nivel abajo, rojo = 2 o más · ♥ = la juegas seguido.")
    st.html(ui.pool_html([ui.owned_tile(n, player, evals, evo=player.cards[n].evo_unlocked,
                                        note=f"valor {evals[n].value:.2f}") for n in names]))
    with st.expander("Tabla"):
        st.dataframe(pd.DataFrame([{
            "Carta": c.es, "Nivel": c.level, "Rareza": c.rarity, "Elixir": c.elixir,
            "Evo": "✨" if c.evo_unlocked else "", "Roles": ", ".join(sorted(c.roles)),
            "Meta": round(evals[n].meta, 2), "Factor nivel": round(evals[n].level_factor, 2),
            "La juegas %": round(100 * player.comfort.get(n, 0.0)), "Valor": round(evals[n].value, 3),
        } for n, c in player.cards.items()]).sort_values("Valor", ascending=False), width="stretch", hide_index=True)

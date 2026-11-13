"""Uso por consola.

Ejemplos:
  python cli.py --demo --mode optimal
  python cli.py --demo --mode archetype --archetype log_bait
  python cli.py --demo --mode war
  python cli.py --demo --mode ranking
  python cli.py --tag "#ABC123" --mode upgrades
  python cli.py --tag "#ABC123" --mode meta --players 150   (descarga batallas reales)
  python cli.py --mode wiki                                 (actualiza los stats de la wiki para el motor v4)
  python cli.py --demo --engine clasico                     (usa el motor v3)
"""
from __future__ import annotations

import argparse
import sys

from crdeck.api import ApiError, fetch_battlelog
from crdeck.battles import BATTLES_PATH, crawl, save_battles
from crdeck.attributes import apply_attributes, point_names
from crdeck.collection import attach_catalog, default_reference_level
from crdeck.comfort import apply_comfort
from crdeck.deck_link import copy_link
from crdeck.loader import ENV_PATH, load_env, load_game_data, load_player
from crdeck.meta import BattleMeta, load_battle_meta
from crdeck.ranking import rank_archetypes
from crdeck.scoring import evaluate_cards
from crdeck.solver import SolveRequest, solve
from crdeck.upgrade import upgrade_advice
from crdeck.wiki import STATS_PATH, WikiError, fetch_all, load_stats, save_stats


def print_deck(i, d, player):
    title = f"Mazo {i}" + (f" — {d['archetype']}" if d.get("archetype") else "")
    print(f"\n=== {title} | puntaje {d['score']:.2f} | elixir {d['avg_elixir']:.1f} ===")
    for c in d["cards"]:
        oc = player.cards[c]
        evo = " [EVO]" if c in d["evos"] else ""
        champ = " [CAMPEÓN]" if oc.champion else ""
        print(f"  - {oc.es:<24} nv {oc.level}{evo}{champ}")
    print("  Valoración: " + ", ".join(f"{k} {v:.1f}" for k, v in d["ratings"].items()))
    if d.get("win"):
        p, lo, hi = d["win"]
        print(f"  Victoria estimada contra un rival típico de tu nivel: {p:.0%} ({lo:.0%}–{hi:.0%})")
    print("  Amenazas: " + ", ".join(f"{t['name']} {t['cov']:.0%}" for t in d["coverage"]))
    for txt, *_ in d["works"][:4]:
        print(f"  ✓ {txt}")
    if d.get("points"):
        names = point_names()
        print("  Puntos por tipo: " + ", ".join(f"{names.get(k, k)} {v:g}"
                                               for k, v in sorted(d["points"].items(), key=lambda kv: -kv[1])))
    for a, b, w, r in d["synergies"]:
        print(f"  {'+' if w > 0 else '−'} {a} + {b} ({w:+.2f}): {r}")
    for w in d["warnings"]:
        print(f"  ⚠ {w}")
    link = copy_link(d["cards"], player)
    if link:
        print(f"  Copiar: {link}")


def print_meta(bm: BattleMeta, game, top: int = 15):
    es = lambda n: game.info(n).es if game.info(n) else n
    print(f"\nMeta: {bm.n_battles} batallas de {bm.n_players} jugadores ({bm.first[:10]} a {bm.last[:10]})")
    print(f"1 nivel medio de ventaja ≈ {bm.level_win_gain * 100:+.1f} puntos de probabilidad de ganar")
    print("\nCartas (meta final; entre paréntesis el de cards.yaml):")
    for n, d in sorted(game.meta_detail.items(), key=lambda kv: -kv[1]["final"])[:top]:
        c = bm.cards[n]
        print(f"  {es(n):<24} {d['final']:.2f} ({d['catalogo']:.2f})  uso {c.usage:5.1%}  "
              f"win rate {c.win_rate:5.1%}  {c.games} partidas")
    measured = sorted((p for p in bm.pairs if p.effect is not None), key=lambda p: -p.effect)
    print("\nPares que más ganan juntos (y los que rinden peor):")
    for p in measured[:10] + measured[-5:]:
        print(f"  {es(p.a)} + {es(p.b)}: {p.effect_points * 100:+.0f} pts de victoria juntas, {p.together} mazos")
    if not measured:
        print("  Aún no hay pares con suficientes mazos; descarga más batallas.")


def main(argv=None):
    # La consola de Windows usa cp1252 y falla con ⚠, −, ♥... Así se imprimen bien en cualquier consola.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    env_found = load_env()
    ap = argparse.ArgumentParser(description="Recomendador de mazos de Clash Royale")
    src = ap.add_mutually_exclusive_group(required="--mode" not in (argv or sys.argv) or
                                          "wiki" not in (argv or sys.argv))
    src.add_argument("--tag")
    src.add_argument("--json", help="Archivo JSON con la respuesta de la API")
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--mode", choices=["optimal", "archetype", "war", "upgrades", "ranking", "meta", "wiki"], default="optimal")
    ap.add_argument("--archetype", help="Clave del arquetipo (ver data/archetypes.yaml)")
    ap.add_argument("--ref-level", type=int, help="Nivel de referencia (por defecto: mediana de tus mejores cartas)")
    ap.add_argument("--level-weight", type=float, default=1.0, help="Importancia del nivel (0 a 2)")
    ap.add_argument("--alternatives", type=int, default=0, help="Mazos alternativos extra (modos optimal/archetype)")
    ap.add_argument("--min-diff", type=int, default=3,
                    help="Cartas que debe cambiar cada alternativa respecto a las anteriores (por defecto 3)")
    ap.add_argument("--time-limit", type=float, default=20.0)
    ap.add_argument("--players", type=int, default=100, help="Modo meta: jugadores cuyo historial se descarga")
    ap.add_argument("--seed-tags", default="", help="Modo meta: tags extra para empezar, separados por comas")
    ap.add_argument("--no-battle-meta", action="store_true", help="Ignora data/battles.json (usa solo los YAML)")
    ap.add_argument("--engine", choices=["atributos", "clasico"],
                    help="Motor: atributos (v4, fichas de la wiki; por defecto si existe data/card_stats.json) o clasico (v3)")
    ap.add_argument("--comfort", type=float, help="Bonus por cartas que ya juegas (por defecto el de rules.yaml; 0 = sin bonus)")
    a = ap.parse_args(argv)

    if a.tag and not env_found:
        sys.exit(f"No encuentro el archivo .env. Debe estar exactamente en: {ENV_PATH}")
    game = load_game_data()
    cfg = game.rules["battle_meta"]
    if a.mode == "wiki":
        names = [c.name for c in game.cards.values()]
        names += [n for n in load_stats().get("cards", {}) if n not in names]   # cartas nuevas ya conocidas
        print(f"Leyendo {len(names)} cartas (con evoluciones y héroes) de la Clash Royale Wiki...")
        try:
            data = fetch_all(names, progress=lambda i, n, name: print(f"  {i}/{n} {name}") if i % 20 == 0 else None)
        except WikiError as e:
            sys.exit(str(e))
        save_stats(data)
        print(f"Guardado en {STATS_PATH}: {len(data['cards'])} cartas. Sin datos: {', '.join(data['missing']) or 'ninguna'}")
        return
    engine = a.engine or ("atributos" if STATS_PATH.exists() else "clasico")
    if engine == "atributos":
        game = apply_attributes(game)
        print("Motor v4 (atributos): fichas de la Clash Royale Wiki. Usa --engine clasico para el motor v3.")
    if a.mode == "meta":
        if not a.tag:
            sys.exit("El modo meta necesita tu --tag (descarga tu historial y el de tus rivales).")
        seeds = [a.tag] + [t for t in a.seed_tags.split(",") if t.strip()]
        print(f"Descargando historiales de hasta {a.players} jugadores...")
        try:
            battles, info = crawl(seeds, a.players, cfg["battle_types"], progress=lambda i, n, nb: (
                print(f"  {i}/{n} jugadores · {nb} batallas") if i % 10 == 0 or i == n else None))
        except ApiError as e:
            sys.exit(str(e))
        total = save_battles(battles, max_age_days=cfg["max_age_days"], cards_info=info["cards"])
        print(f"{len(battles)} batallas descargadas ({info['errors']} jugadores con error). "
              f"Total guardado en {BATTLES_PATH}: {total}")
        game, bm = load_battle_meta(game)
        if bm:
            print_meta(bm, game)
        return
    if not a.no_battle_meta:
        game, bm = load_battle_meta(game)
        if bm:
            print(f"Meta de batallas reales: {bm.n_battles} batallas ({bm.first[:10]} a {bm.last[:10]}). "
                  "Usa --no-battle-meta para ignorarlo.")
    try:
        player = load_player(game, tag=a.tag, json_path=a.json, demo=a.demo)
    except ApiError as e:
        sys.exit(str(e))
    log = None
    if a.tag:
        try:
            log = fetch_battlelog(a.tag)
        except ApiError as e:
            print(f"No se pudo leer tu historial (solo se usa tu mazo actual): {e}")
    attach_catalog(player, game)
    apply_comfort(player, log, game.rules["comfort"])
    comfort = game.rules["comfort"]["weight"] if a.comfort is None else a.comfort
    ref = a.ref_level or default_reference_level(player)
    print(f"Jugador: {player.name} ({player.tag}) | {len(player.cards)} cartas | nivel de referencia {ref}")
    if player.unknown_cards:
        print(f"Cartas sin metadatos en cards.yaml: {', '.join(player.unknown_cards)}")
    if player.comfort and comfort:
        top = sorted(player.comfort.items(), key=lambda kv: -kv[1])[:8]
        print(f"Bonus {comfort:g} por cartas que ya juegas (según {player.comfort_source}): "
              + ", ".join(f"{player.cards[c].es} {f:.0%}" for c, f in top))

    evals = evaluate_cards(player, game, ref, a.level_weight, comfort)
    if a.mode == "ranking":
        best, rows = rank_archetypes(player, game, evals, time_limit=min(a.time_limit, 10.0))
        print("\nRanking de arquetipos" + (f" (óptimo libre: {best:.2f})" if best is not None else ""))
        for pos, r in enumerate(rows, 1):
            if r.ok:
                delta = f"{r.score - best:+.2f}" if best is not None else ""
                cards = ", ".join(player.cards[c].es for c in r.deck["cards"])
                print(f"  {pos:>2}. {r.name:<26} {r.score:5.2f} ({delta})  elixir {r.deck['avg_elixir']:.1f}  {cards}")
            else:
                print(f"   -  {r.name:<26} no disponible: {r.note}")
        return
    if a.mode == "war":
        req = SolveRequest(n_decks=4, war_unique=True, time_limit=a.time_limit)
    else:
        arch = [a.archetype] if a.mode == "archetype" else []
        if a.mode == "archetype" and a.archetype not in game.archetypes:
            sys.exit(f"Arquetipo desconocido. Opciones: {', '.join(game.archetypes)}")
        req = SolveRequest(n_decks=1, archetypes=arch, min_diff=a.min_diff, time_limit=a.time_limit)

    if a.mode == "upgrades":
        for r in upgrade_advice(player, game, ref, a.level_weight, req, comfort_weight=comfort):
            print(f"  {r['carta']:<24} nv {r['nivel_actual']} → +1 : {r['ganancia']:+.3f}")
        return

    shown = []
    for k in range(1 + (a.alternatives if a.mode != "war" else 0)):
        req.exclude_decks = shown
        res = solve(player, game, evals, req)
        for n in res.notes:
            print(f"Nota: {n}")
        if not res.ok:
            break
        for i, d in enumerate(res.decks, 1):
            print_deck(i if a.mode == "war" else k + 1, d, player)
        shown = shown + [d["cards"] for d in res.decks]


if __name__ == "__main__":
    main()

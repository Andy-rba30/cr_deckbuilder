"""Uso por consola.

Ejemplos:
  python cli.py --demo --mode optimal
  python cli.py --demo --mode archetype --archetype log_bait
  python cli.py --demo --mode war
  python cli.py --tag "#ABC123" --mode upgrades
"""
from __future__ import annotations

import argparse
import sys

from crdeck.api import ApiError
from crdeck.collection import default_reference_level
from crdeck.deck_link import copy_link
from crdeck.loader import ENV_PATH, load_env, load_game_data, load_player
from crdeck.scoring import evaluate_cards
from crdeck.solver import SolveRequest, solve
from crdeck.upgrade import upgrade_advice


def print_deck(i, d, player):
    title = f"Mazo {i}" + (f" — {d['archetype']}" if d.get("archetype") else "")
    print(f"\n=== {title} | puntaje {d['score']:.2f} | elixir {d['avg_elixir']:.1f} ===")
    for c in d["cards"]:
        oc = player.cards[c]
        evo = " [EVO]" if c in d["evos"] else ""
        champ = " [CAMPEÓN]" if oc.champion else ""
        print(f"  - {oc.es:<24} nv {oc.level}{evo}{champ}")
    print("  Valoración: " + ", ".join(f"{k} {v:.1f}" for k, v in d["ratings"].items()))
    for a, b, w, r in d["synergies"]:
        print(f"  {'+' if w > 0 else '−'} {a} + {b} ({w:+.2f}): {r}")
    for w in d["warnings"]:
        print(f"  ⚠ {w}")
    link = copy_link(d["cards"], player)
    if link:
        print(f"  Copiar: {link}")


def main(argv=None):
    env_found = load_env()
    ap = argparse.ArgumentParser(description="Recomendador de mazos de Clash Royale")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tag")
    src.add_argument("--json", help="Archivo JSON con la respuesta de la API")
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--mode", choices=["optimal", "archetype", "war", "upgrades"], default="optimal")
    ap.add_argument("--archetype", help="Clave del arquetipo (ver data/archetypes.yaml)")
    ap.add_argument("--ref-level", type=int, help="Nivel de referencia (por defecto: mediana de tus mejores cartas)")
    ap.add_argument("--level-weight", type=float, default=1.0, help="Importancia del nivel (0 a 2)")
    ap.add_argument("--alternatives", type=int, default=0, help="Mazos alternativos extra (modos optimal/archetype)")
    ap.add_argument("--time-limit", type=float, default=20.0)
    a = ap.parse_args(argv)

    if a.tag and not env_found:
        sys.exit(f"No encuentro el archivo .env. Debe estar exactamente en: {ENV_PATH}")
    game = load_game_data()
    try:
        player = load_player(game, tag=a.tag, json_path=a.json, demo=a.demo)
    except ApiError as e:
        sys.exit(str(e))
    ref = a.ref_level or default_reference_level(player)
    print(f"Jugador: {player.name} ({player.tag}) | {len(player.cards)} cartas | nivel de referencia {ref}")
    if player.unknown_cards:
        print(f"Cartas sin metadatos en cards.yaml: {', '.join(player.unknown_cards)}")

    evals = evaluate_cards(player, game, ref, a.level_weight)
    if a.mode == "war":
        req = SolveRequest(n_decks=4, war_unique=True, time_limit=a.time_limit)
    else:
        arch = [a.archetype] if a.mode == "archetype" else []
        if a.mode == "archetype" and a.archetype not in game.archetypes:
            sys.exit(f"Arquetipo desconocido. Opciones: {', '.join(game.archetypes)}")
        req = SolveRequest(n_decks=1, archetypes=arch, time_limit=a.time_limit)

    if a.mode == "upgrades":
        for r in upgrade_advice(player, game, ref, a.level_weight, req):
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

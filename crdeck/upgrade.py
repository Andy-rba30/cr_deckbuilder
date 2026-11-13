"""Asesor de mejoras: ¿qué carta conviene subir de nivel primero?"""
from __future__ import annotations

import copy

from .catalog import GameData
from .collection import Player
from .scoring import evaluate_cards
from .solver import SolveRequest, solve


def upgrade_advice(player: Player, game: GameData, ref_level: int, level_weight: float,
                   req: SolveRequest, top_k: int = 10, time_limit: float = 5.0,
                   comfort_weight: float = 0.0) -> list[dict]:
    base_evals = evaluate_cards(player, game, ref_level, level_weight, comfort_weight)
    base = solve(player, game, base_evals, req)
    if not base.ok:
        return []
    base_score = sum(d["score"] for d in base.decks)

    # Candidatas: las del mazo actual + las cartas con mejor meta que estén bajas de nivel.
    in_deck = {c for d in base.decks for c in d["cards"]}
    others = sorted(
        (n for n in player.cards if n not in in_deck and player.cards[n].level < player.max_level),
        key=lambda n: -base_evals[n].meta,
    )
    candidates = [n for n in in_deck if player.cards[n].level < player.max_level] + others
    candidates = candidates[:top_k]

    fast = copy.copy(req)
    fast.time_limit = time_limit
    results = []
    for name in candidates:
        p2 = copy.deepcopy(player)
        p2.cards[name].level += 1
        r = solve(p2, game, evaluate_cards(p2, game, ref_level, level_weight, comfort_weight), fast)
        if r.ok:
            gain = sum(d["score"] for d in r.decks) - base_score
            results.append({"carta": player.cards[name].es, "nivel_actual": player.cards[name].level,
                            "ganancia": round(gain, 3), "nombre_api": name})
    return sorted(results, key=lambda r: -r["ganancia"])

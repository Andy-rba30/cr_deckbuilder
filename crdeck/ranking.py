"""Ranking de arquetipos: arma la mejor variante de cada uno con tu colección y los ordena."""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import GameData
from .collection import Player
from .scoring import CardEval
from .solver import SolveRequest, solve


@dataclass
class ArchetypeRank:
    key: str
    name: str
    ok: bool
    score: float | None        # None si no se pudo armar
    deck: dict | None          # resultado de evaluate_deck
    note: str                  # motivo si no se pudo armar, o avisos del solver


def rank_archetypes(player: Player, game: GameData, evals: dict[str, CardEval],
                    locked: list[str] | None = None, banned: list[str] | None = None,
                    time_limit: float = 10.0) -> tuple[float | None, list[ArchetypeRank]]:
    """Devuelve (puntaje del óptimo libre, arquetipos de mejor a peor; los imposibles al final)."""
    def req(archetypes):
        return SolveRequest(archetypes=archetypes, locked=list(locked or []), banned=list(banned or []),
                            time_limit=time_limit)

    free = solve(player, game, evals, req([]))
    best = free.decks[0]["score"] if free.ok else None

    rows = []
    for key, arch in game.archetypes.items():
        r = solve(player, game, evals, req([key]))
        if r.ok:
            d = r.decks[0]
            rows.append(ArchetypeRank(key, arch["name"], True, d["score"], d, " ".join(r.notes)))
        else:
            rows.append(ArchetypeRank(key, arch["name"], False, None, None, " ".join(r.notes)))
    rows.sort(key=lambda a: (not a.ok, -(a.score or 0.0)))
    return best, rows

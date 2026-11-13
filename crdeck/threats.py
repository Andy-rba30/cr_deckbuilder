"""Respuesta a amenazas: qué tan bien cubre un mazo los ataques típicos (data/threats.yaml)."""
from __future__ import annotations

from .catalog import GameData, norm
from .collection import Player


def answers(game: GameData, player: Player) -> dict[str, dict[str, float]]:
    """{amenaza: {carta: 0..1}} para las cartas del jugador (solo las que responden algo)."""
    out = {}
    for key, t in game.threats.get("threats", {}).items():
        exact = {norm(n): float(v) for n, v in (t.get("cards") or {}).items()}
        roles = t.get("roles") or {}
        out[key] = {}
        for name, c in player.cards.items():
            a = exact.get(norm(name))
            if a is None:
                a = max((float(roles.get(r, 0.0)) for r in c.roles), default=0.0)
            if a > 0:
                out[key][name] = a
    return out


def coverage(deck: list[str], game: GameData, ans: dict[str, dict[str, float]]) -> list[dict]:
    """Por amenaza: cobertura 0..1 (suma de respuestas / need) y qué cartas la cubren."""
    out = []
    for key, t in game.threats.get("threats", {}).items():
        by = sorted(((c, ans[key][c]) for c in deck if c in ans.get(key, {})), key=lambda ca: -ca[1])
        cov = min(1.0, sum(a for _, a in by) / float(t["need"]))
        out.append({"key": key, "name": t["name"], "examples": t.get("examples", ""), "cov": cov, "by": by})
    return out

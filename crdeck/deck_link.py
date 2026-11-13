"""Enlace para copiar el mazo al juego."""
from __future__ import annotations

from .collection import Player


def copy_link(deck: list[str], player: Player, lang: str = "es") -> str | None:
    ids = [player.cards[c].id for c in deck]
    if any(i is None for i in ids):
        return None
    # El orden importa: los primeros espacios son los de evolución.
    return f"https://link.clashroyale.com/deck/{lang}?deck=" + ";".join(str(i) for i in ids)

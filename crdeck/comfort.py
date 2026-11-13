"""Bonus por cartas que ya juegas: sabes usarlas, así que valen un poco más para ti.

Qué tanto juegas cada carta = fracción de tus últimas batallas (historial de la API) en las que
iba en tu mazo. Las cartas de tu mazo equipado cuentan al menos como `current_deck` (rules.yaml),
así funciona también sin historial (archivo JSON o demo).
"""
from __future__ import annotations

from collections import Counter

from .collection import Player

# Modos en los que el mazo no lo eliges tú (draft, mazos fijos): no dicen nada de tus gustos.
NOT_CHOSEN = ("draft", "predefined")


def _tag(t: str | None) -> str:
    return (t or "").upper().replace("#", "").replace("O", "0")


def familiarity(player_tag: str, battlelog: list[dict], current_deck: list[str],
                current_floor: float = 0.6) -> tuple[dict[str, float], int]:
    """Devuelve ({carta: 0..1}, batallas contadas)."""
    me_tag, counts, n = _tag(player_tag), Counter(), 0
    for b in battlelog:
        if any(k in str(b.get("deckSelection", "")).lower() for k in NOT_CHOSEN):
            continue
        me = next((p for p in b.get("team") or [] if _tag(p.get("tag")) == me_tag), None)
        cards = (me or {}).get("cards") or []
        if len(cards) != 8:
            continue
        n += 1
        counts.update({c["name"] for c in cards})
    fam = {c: k / n for c, k in counts.items()} if n else {}
    for c in current_deck:
        fam[c] = max(fam.get(c, 0.0), current_floor)
    return fam, n


def apply_comfort(player: Player, battlelog: list[dict] | None, cfg: dict) -> Player:
    """Guarda en el jugador qué tanto juega cada carta y de dónde salió el dato."""
    fam, n = familiarity(player.tag, battlelog or [], player.current_deck, cfg["current_deck"])
    player.comfort = {c: f for c, f in fam.items() if c in player.cards}
    parts = ([f"tus últimas {n} batallas"] if n else []) + (["tu mazo actual"] if player.current_deck else [])
    player.comfort_source = " y ".join(parts)
    return player

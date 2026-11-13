"""Reemplazos sugeridos: para cada carta de un mazo, la mejor carta tuya para cambiarla."""
from __future__ import annotations

from .catalog import GameData, norm
from .collection import Player
from .scoring import CardEval, evaluate_deck, pick_evos, rule_checks, synergy_index
from .needs import profiles
from .threats import answers

PART_NAMES = {"cartas": "cartas", "comodidad": "cartas que juegas", "evoluciones": "evoluciones",
              "sinergias": "sinergias", "complementos": "complementos", "roles": "roles",
              "amenazas": "cobertura", "recomendaciones": "recomendaciones"}


def suggest_swaps(deck: list[str], player: Player, game: GameData, evals: dict[str, CardEval],
                  locked: list[str] = (), banned: list[str] = (), min_gain: float = 0.01) -> list[dict]:
    """Mejor cambio por cada carta del mazo que suba el puntaje y respete las reglas del mazo.

    Devuelve [{out, in, gain, base, new, why, win_before, win_after}] de mayor a menor ganancia.
    """
    syn_idx = synergy_index(game, set(player.cards))
    ans = answers(game, player)
    prof = profiles(game, player)
    slots = game.rules["deck"]["evo_slots"]

    def score(cards):
        return evaluate_deck(cards, pick_evos(cards, player, evals, slots), player, game, evals, syn_idx, ans, prof)

    base = score(deck)
    fixed = {norm(c) for c in locked}
    ban = {norm(c) for c in banned}
    pool = [c for c in player.cards if c not in deck and norm(c) not in ban]
    options = []   # (ganancia, sale, entra, mazo evaluado)
    for old in deck:
        if norm(old) in fixed:
            continue
        cands = []
        for new in pool:
            cards = [new if c == old else c for c in deck]
            if not all(ok for _, ok, hard in rule_checks(cards, player, game) if hard):
                continue
            d = score(cards)
            if d["score"] - base["score"] >= min_gain:
                cands.append((d["score"] - base["score"], old, new, d))
        options += sorted(cands, key=lambda o: -o[0])[:8]

    # Una sugerencia por carta que sale y sin repetir la que entra (si no, todas proponen la misma).
    out, used_out, used_in = [], set(), set()
    for gain, old, new, d in sorted(options, key=lambda o: -o[0]):
        if old in used_out or new in used_in:
            continue
        used_out.add(old)
        used_in.add(new)
        deltas = sorted(((d["parts"][k] - base["parts"][k], k) for k in d["parts"]), reverse=True)
        why = ", ".join(f"{PART_NAMES[k]} {v:+.2f}" for v, k in deltas if v > 0.005)[:80]
        out.append({"out": old, "in": new, "gain": gain, "base": base, "new": d, "why": why,
                    "win_before": base["win"], "win_after": d["win"]})
    return out

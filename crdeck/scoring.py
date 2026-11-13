"""Valor de cada carta (meta × nivel − puntos de quiebre) y evaluación completa de un mazo."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .catalog import GameData, norm
from .collection import Player


@dataclass
class CardEval:
    name: str
    value: float               # valor que usa el solver
    meta: float
    level_factor: float
    gap: int                   # nivel de referencia − nivel de la carta
    bp_penalty: float
    evo_bonus: float           # solo > 0 si la evolución está desbloqueada
    comfort: float = 0.0       # bonus por ser una carta que ya juegas (incluido en value)
    warnings: list[str] = field(default_factory=list)


def level_factor(level: int, ref: int, sens: float, rules: dict, level_weight: float = 1.0) -> float:
    lv = rules["level"]
    gap = ref - level
    if gap <= 0:
        return 1.0 + min(-gap, lv["over_bonus_cap"]) * lv["over_bonus_per_level"] * level_weight
    s = min(1.0, sens * level_weight)
    return max(0.0, 1.0 - s * (1.0 - math.exp(-lv["curve"] * gap)))


def evaluate_cards(player: Player, game: GameData, ref_level: int, level_weight: float = 1.0,
                   comfort_weight: float = 0.0) -> dict[str, CardEval]:
    """comfort_weight: bonus para una carta que usas en el 100% de tus batallas (ver crdeck/comfort.py)."""
    rules = game.rules
    unknown = rules["unknown_card"]
    out: dict[str, CardEval] = {}
    for name, c in player.cards.items():
        info = game.info(name)   # del catálogo activo: puede traer el meta ajustado con batallas reales
        meta = info.meta if info else game.unknown_meta.get(norm(name), unknown["meta"])
        sens = info.sens if info else unknown["sens"]
        lf = level_factor(c.level, ref_level, sens, rules, level_weight)
        evo = 0.0
        if c.evo_unlocked:
            evo = (info.evo_bonus if info and info.evo_bonus > 0 else rules["evo_bonus_default"]) * lf
        bonus = comfort_weight * player.comfort.get(name, 0.0)
        value = meta * lf + (rules["champion_bonus"] if c.champion else 0.0) + bonus
        out[name] = CardEval(name, value, meta, lf, ref_level - c.level, 0.0, evo, bonus)

    # Puntos de quiebre: comparamos tu carta contra la del rival al nivel de referencia.
    pen = rules["level"]["breakpoint_penalty"] * level_weight
    by_norm = {norm(n): n for n in player.cards}
    for it in game.interactions:
        tag = "" if it.verified else " (dato sin verificar)"
        tgt = by_norm.get(norm(it.target))
        if tgt:  # ¿tu objetivo muere ante el atacante rival y a igual nivel no moriría?
            t = player.cards[tgt].level
            if (ref_level - t) >= it.k and not (0 >= it.k):
                e = out[tgt]
                e.bp_penalty += pen
                e.value -= pen
                e.warnings.append(f"Tu {player.cards[tgt].es} (nv {t}) muere ante {it.attacker} rival de nv {ref_level}{tag}")
        att = by_norm.get(norm(it.attacker))
        if att:  # ¿tu hechizo ya no mata al objetivo rival que a igual nivel sí mataría?
            a = player.cards[att].level
            if (0 >= it.k) and not ((a - ref_level) >= it.k):
                e = out[att]
                e.bp_penalty += pen
                e.value -= pen
                e.warnings.append(f"Tu {player.cards[att].es} (nv {a}) ya no mata a {it.target} rival de nv {ref_level}{tag}")
    for e in out.values():
        e.value = max(0.0, e.value)
    return out


def synergy_index(game: GameData, owned: set[str]) -> dict[tuple[str, str], tuple[float, str]]:
    """Sinergias limitadas a las cartas que tienes, con claves en nombres de la API."""
    by_norm = {norm(n): n for n in owned}
    idx = {}
    for s in game.synergies:
        a, b = by_norm.get(norm(s.a)), by_norm.get(norm(s.b))
        if a and b and a != b:
            key = tuple(sorted((a, b)))
            w, r = idx.get(key, (0.0, ""))
            idx[key] = (w + s.weight, r or s.reason)
    return idx


# ---------------------------------------------------------------- evaluación de un mazo
ATTACK_ROLES = {"win_condition", "big_spell", "dps", "ranged_dps", "support", "bait"}
DEFENSE_ROLES = {"air_defense", "building", "anti_tank_dps", "mini_tank", "cheap_defense", "splash"}


def _sat(x: float, k: float) -> float:
    return 10.0 * (1.0 - math.exp(-max(0.0, x) / k))


def evaluate_deck(deck: list[str], evos: list[str], player: Player, game: GameData,
                  evals: dict[str, CardEval]) -> dict:
    rules = game.rules
    cards = [player.cards[n] for n in deck]
    comfort_part = sum(evals[n].comfort for n in deck)
    card_part = sum(evals[n].value for n in deck) - comfort_part
    evo_part = sum(evals[n].evo_bonus for n in evos)

    syn_idx = synergy_index(game, set(deck))
    active = [(a, b, w, r) for (a, b), (w, r) in syn_idx.items()]
    syn_part = sum(w for _, _, w, _ in active)

    roles_present = set().union(*(c.roles for c in cards))
    bonuses = [(rb["name"], rb["bonus"], bool(roles_present & set(rb["any_roles"]))) for rb in rules["role_bonuses"]]
    role_part = sum(b for _, b, ok in bonuses if ok)

    total = card_part + comfort_part + evo_part + syn_part + role_part

    atk = sum(evals[c.name].value for c in cards if c.roles & ATTACK_ROLES)
    dfn = sum(evals[c.name].value for c in cards if c.roles & DEFENSE_ROLES)
    air = sum(1 for c in cards if "air_defense" in c.roles)
    versatility = (sum(1 for *_, ok in bonuses if ok) + min(air, 3) / 3) / (len(bonuses) + 1)

    warnings = [w for n in deck for w in evals[n].warnings]
    for c in cards:
        if evals[c.name].gap >= 2:
            warnings.append(f"{c.es} está {evals[c.name].gap} niveles bajo tu referencia")

    return {
        "cards": deck,
        "evos": evos,
        "avg_elixir": sum(c.elixir for c in cards) / len(cards),
        "score": total,
        "parts": {"cartas": card_part, "comodidad": comfort_part, "evoluciones": evo_part,
                  "sinergias": syn_part, "roles": role_part},
        "ratings": {   # heurísticas propias de 0 a 10
            "Ataque": _sat(atk, 1.2),
            "Defensa": _sat(dfn, 2.0),
            "Sinergia": _sat(syn_part, 0.5),
            "Versatilidad": 10.0 * versatility,
        },
        "synergies": [(player.cards[a].es, player.cards[b].es, w, r) for a, b, w, r in active],
        "role_checks": bonuses,
        "warnings": warnings,
    }


def pick_evos(cards: list[str], player: Player, evals: dict[str, CardEval], slots: int) -> list[str]:
    """Para un mazo armado a mano: las evoluciones desbloqueadas con más bonus, hasta llenar los espacios."""
    evo = [c for c in cards if player.cards[c].evo_unlocked]
    return sorted(evo, key=lambda c: -evals[c].evo_bonus)[:slots]

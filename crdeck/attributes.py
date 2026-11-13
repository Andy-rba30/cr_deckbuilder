"""Motor v4 (atributos): fichas de puntos por carta a partir de los stats de la wiki, y reglas sobre ellas.

1. Stats de la wiki (data/card_stats.json) → resumen (vida, daño, alcance, objetivo, habilidades...).
2. Resumen → FICHA de puntos 0..10 por tipo (fórmulas de data/attribute_rules.yaml).
3. Reglas sobre las fichas → necesidades y quién las cubre, respuesta a amenazas, sinergias entre pares,
   roles de las cartas nuevas y puntos de quiebre reales. Se generan en el mismo formato que usa el
   motor clásico, así el resto del programa (modelo, interfaz) funciona igual.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import yaml

from .catalog import DATA_DIR, CardInfo, GameData, Interaction, Synergy, norm
from .wiki import STATS_PATH, load_stats

RULES_PATH = DATA_DIR / "attribute_rules.yaml"

ABILITY_FLAGS = {   # habilidad en card_stats.json -> variable en las fórmulas
    "stun": "aturde", "freeze": "congela", "slow": "ralentiza", "knockback": "empuja", "reset": "reinicia",
    "pull": "atrae", "spawner": "invoca", "charge": "carga", "dash": "carga", "jump": "salta", "shield": "escudo",
    "heal": "cura", "rage": "furia", "invisible": "invisible", "taunt": "provoca", "parry": "desvia",
    "damage_reduction": "reduce_dano", "ramp": "rampa", "tunnel": "tunel", "root": "raiz",
    "death_damage": "dano_muerte", "chain": "cadena",
}
ROLE_NAMES = ["win_condition", "tank", "mini_tank", "building", "air_defense", "small_spell", "big_spell", "splash",
              "anti_tank_dps", "dps", "ranged_dps", "support", "cycle", "cheap_defense", "swarm", "bait", "reset"]


# ---------------------------------------------------------------- fórmulas seguras
def _escala(x, lo, hi):
    if hi == lo:
        return 0.0
    return 10.0 * min(1.0, max(0.0, (x - lo) / (hi - lo)))


def _escala_log(x, lo, hi):
    return _escala(math.log(max(x, 1e-9)), math.log(lo), math.log(hi)) if x > 0 else 0.0


def _clip(x, lo=0.0, hi=1.0):
    return min(hi, max(lo, x))


FUNCS = {"escala": _escala, "escala_log": _escala_log, "clip": _clip, "min": min, "max": max, "abs": abs}
_ALLOWED = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp, ast.Call, ast.Name,
            ast.Load, ast.Constant, ast.Attribute, ast.And, ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.USub, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)


class RuleError(ValueError):
    pass


def compile_expr(expr: str):
    """Compila una fórmula de attribute_rules.yaml permitiendo solo operaciones simples (sin código)."""
    tree = ast.parse(str(expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise RuleError(f"Fórmula no permitida ({type(node).__name__}): {expr}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in FUNCS):
            raise RuleError(f"Función no permitida en: {expr}")
        if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id in ("a", "b")):
            raise RuleError(f"Solo se puede usar a.<x> y b.<x> en: {expr}")
    return compile(tree, "<regla>", "eval")


def evaluate(code, variables: dict) -> float:
    try:
        return float(eval(code, {"__builtins__": {}}, {**FUNCS, **variables}))  # noqa: S307 (fórmula validada)
    except NameError as e:
        raise RuleError(f"Variable desconocida en una regla: {e}") from e


# ---------------------------------------------------------------- stats → resumen
def _num(v, default=0.0) -> float:
    return float(v) if isinstance(v, (int, float)) else default


def _units(entry: dict) -> dict[str, dict]:
    """Agrupa los stats por tropa ('' = la principal): vida, dps, daño, cantidad."""
    st, title = entry.get("stats", {}), entry.get("title", "").lower().rstrip(".")
    counts = {"": _num(entry["attributes"].get("Count"), 1.0)}
    for sec in entry.get("secondary", []):
        name = re.sub(r"\s*attributes\s*$", "", str(sec.get("section", "")), flags=re.I).strip().lower()
        if name and "Count" in sec:
            counts[name] = _num(sec["Count"], 1.0)
    units: dict[str, dict] = {}
    for key, val in st.items():
        if not isinstance(val, (int, float)):
            continue
        k = key.lower()
        if "stage" in k and not k.startswith("2 stage"):      # Infernos: se usa la etapa 2 como referencia
            continue
        k = k.replace("2 stage ", "")
        m = re.fullmatch(r"(.*?)\s*(hitpoints|damage per second|area damage|damage)", k)
        if not m or "lost" in k or "shield" in k or "tower" in k or "building" in k or "death" in k:
            continue
        prefix = m.group(1).strip()
        if prefix == title:
            prefix = ""
        u = units.setdefault(prefix, {})
        field_ = {"hitpoints": "hp", "damage per second": "dps", "area damage": "dmg", "damage": "dmg"}[m.group(2)]
        u.setdefault(field_, val)
    for prefix, u in units.items():
        u["count"] = counts.get(prefix, counts[""] if prefix == "" else 1.0)
    return units


def summarize(entry: dict, info: CardInfo | None = None) -> dict:
    """Variables de las fórmulas para una carta (o para su evolución / héroe)."""
    a, st = entry.get("attributes", {}), entry.get("stats", {})
    typ = str(a.get("Type", "")).lower()
    if not typ and info:   # la wiki no trae la tabla de atributos (p. ej. Rayo, Veneno): usa el catálogo
        typ = "spell" if info.roles & {"small_spell", "big_spell"} else "building" if "building" in info.roles else "troop"
    hechizo, edificio = float("spell" in typ), float("building" in typ)
    units = _units(entry)
    if hechizo and any(u.get("hp") for u in units.values()) and not _num(st.get("Area Damage")):
        hechizo = 0.0   # "hechizo" que solo despliega tropas (Barril de duendes, Cementerio): se comporta como tropa
    tropa = float(not hechizo and not edificio)
    target = str(a.get("Target", "Air & Ground" if hechizo else "Ground")).lower()
    cost = _num(a.get("Cost"), info.elixir if info else 4.0)
    hp = sum(_num(u.get("hp")) * u["count"] for u in units.values()) + _num(st.get("Shield Hitpoints"))
    hit = _num(a.get("Hit Speed"), 1.0) or 1.0
    dps = sum((_num(u.get("dps")) or _num(u.get("dmg")) / hit) * u["count"] for u in units.values())
    area_dmg = _num(st.get("Area Damage"))
    radius = max(_num(a.get("Splash Radius")), _num(a.get("Radius")), _num(a.get("Death Damage Splash Radius")))
    if hechizo and not radius and _num(a.get("Range")):
        radius = min(3.5, _num(a.get("Range")) / 3)   # hechizos que ruedan (El Tronco): su recorrido hace de área
    v = {
        "coste": cost, "hp": hp if not hechizo else 0.0, "dps": dps if not hechizo else 0.0,
        "dano_hechizo": area_dmg if hechizo else 0.0, "dano_torre": _num(st.get("Crown Tower Damage")),
        "dano_edificios": _num(st.get("Building Damage")), "radio": radius, "rango": _num(a.get("Range")),
        "vel": _num(a.get("Speed")), "cantidad": sum(u["count"] for u in units.values() if u.get("hp")) or 1.0,
        "tropa": tropa, "edificio": edificio, "hechizo": hechizo,
        "aereo": float(str(a.get("Transport", "")).lower() == "air"),
        "ataca_aire": float("air" in target), "ataca_edificios": float(target.startswith("building")),
        "area": float(bool(area_dmg or _num(a.get("Splash Radius")))),   # el daño al morir no cuenta
    }
    v.update({flag: 0.0 for flag in set(ABILITY_FLAGS.values())})
    for ab in entry.get("abilities", []):
        if ab in ABILITY_FLAGS:
            v[ABILITY_FLAGS[ab]] = 1.0
    v.update({f"rol_{r}": float(bool(info and r in info.roles)) for r in ROLE_NAMES})
    return v


# ---------------------------------------------------------------- fichas
@dataclass
class Ficha:
    name: str
    points: dict[str, float]          # tanque, dano, ... (0..10)
    variables: dict[str, float]       # stats + tipo + habilidades + puntos (lo que ven las fórmulas)
    abilities: list[str]
    url: str = ""
    evolution: dict[str, float] | None = None   # puntos de la evolución (si existe)
    hero: dict[str, float] | None = None        # puntos del héroe (si existe)
    variant_abilities: dict[str, list[str]] = field(default_factory=dict)


def _points(variables: dict, compiled: dict) -> dict[str, float]:
    return {k: round(_clip(evaluate(code, variables), 0.0, 10.0), 2) for k, code in compiled.items()}


def build_fichas(stats: dict, game: GameData, rules: dict) -> dict[str, Ficha]:
    compiled = {k: compile_expr(p["expr"]) for k, p in rules["points"].items()}
    bonus = rules.get("variant_bonus", {})
    out = {}
    for name, entry in stats.get("cards", {}).items():
        info = game.info(name)
        variables = summarize(entry, info)
        pts = _points(variables, compiled)
        f = Ficha(name, pts, {**variables, **pts}, list(entry.get("abilities", [])), entry.get("url", ""))
        for kind in ("evolution", "hero"):
            if kind not in entry:
                continue
            var = summarize(entry[kind], info)
            vp = _points(var, compiled)
            vp = {k: max(vp[k], pts[k]) for k in pts}                    # nunca peor que la carta normal
            new_abilities = sorted(set(entry[kind].get("abilities", [])) - set(f.abilities))
            for ab in new_abilities:
                for k, plus in bonus.get(ABILITY_FLAGS.get(ab, ab), {}).items():
                    vp[k] = round(min(10.0, vp[k] + plus), 2)
            setattr(f, kind, vp)
            f.variant_abilities[kind] = new_abilities
        out[norm(name)] = f
    return out


# ---------------------------------------------------------------- reglas → datos del motor
def derived_roles(f: Ficha, rules: dict) -> frozenset:
    return frozenset(r for r, expr in rules.get("roles", {}).items() if evaluate(compile_expr(expr), f.variables) > 0)


def _need_maps(fichas: dict[str, Ficha], rules: dict) -> dict:
    needs = {}
    for key, n in rules.get("needs", {}).items():
        need_c, prov_c = compile_expr(n["need"]), compile_expr(n["provide"])
        cards, providers = {}, {}
        for f in fichas.values():
            a, p = _clip(evaluate(need_c, f.variables)), _clip(evaluate(prov_c, f.variables))
            if a >= 0.05:
                cards[f.name] = round(a, 2)
            if p >= 0.05:
                providers[f.name] = round(p, 2)
        needs[key] = {"name": n["name"], "good": n["good"], "bad": n["bad"], "need": n.get("need_total", 1.0),
                      "cards": cards, "providers": providers}
    return {"weight": rules.get("weight", 0.2), "warn_below": rules.get("warn_below", 0.5), "needs": needs}


def _threat_maps(fichas: dict[str, Ficha], rules: dict) -> dict:
    threats = {}
    for key, t in rules.get("threats", {}).items():
        code = compile_expr(t["answer"])
        cards = {f.name: round(_clip(evaluate(code, f.variables)), 2) for f in fichas.values()}
        threats[key] = {"name": t["name"], "need": t["need"], "examples": t.get("examples", ""),
                        "cards": {c: v for c, v in cards.items() if v > 0}}
    return {"weight": rules.get("threat_weight", 0.15), "warn_below": rules.get("threat_warn_below", 0.5),
            "threats": threats}


def _pair_synergies(fichas: dict[str, Ficha], rules: dict) -> list[Synergy]:
    compiled = [(r, compile_expr(r["when"])) for r in rules.get("pairs", [])]
    if not compiled:
        return []
    out = []
    names = sorted(fichas)
    for x, y in combinations(names, 2):
        fa, fb = fichas[x], fichas[y]
        for (r, code) in compiled:
            ns = {"a": SimpleNamespace(**fa.variables), "b": SimpleNamespace(**fb.variables)}
            ns2 = {"a": SimpleNamespace(**fb.variables), "b": SimpleNamespace(**fa.variables)}
            if evaluate(code, ns) > 0 or evaluate(code, ns2) > 0:
                out.append(Synergy(fa.name, fb.name, float(r["value"]), r.get("reason", r["name"]), "atributos"))
    return out


def _breakpoints(stats: dict, fichas: dict[str, Ficha], rules: dict) -> list[Interaction]:
    """Con +10% por nivel: el hechizo mata a la tropa cuando daño·1.1^(nivel_hechizo − nivel_tropa) ≥ vida."""
    cfg = rules.get("breakpoints", {})
    max_diff = cfg.get("max_diff", 2)
    out = []
    cards = stats.get("cards", {})
    for spell in cfg.get("spells", []):
        s = cards.get(spell)
        dmg = _num((s or {}).get("stats", {}).get("Area Damage"))
        if not dmg:
            continue
        for name, entry in cards.items():
            f = fichas.get(norm(name))
            if not f or not f.variables["tropa"]:
                continue
            units = _units(entry)
            hp = max((_num(u.get("hp")) for u in units.values()), default=0.0)   # la tropa más resistente
            if hp <= 0:
                continue
            k = math.ceil(math.log(hp / dmg) / math.log(1.1) - 1e-9)       # niveles de ventaja que necesita
            if -max_diff <= k <= max_diff:
                out.append(Interaction(spell, name, k, True))
    return out


def load_rules(path: Path = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def apply_attributes(game: GameData, stats: dict | None = None, rules: dict | None = None) -> GameData:
    """Catálogo para el motor v4: reglas generadas desde las fichas de la wiki. Sin stats, no cambia nada."""
    stats = stats if stats is not None else load_stats(STATS_PATH)
    if not stats.get("cards"):
        return game
    rules = rules if rules is not None else load_rules()
    fichas = build_fichas(stats, game, rules)

    cards = dict(game.cards)
    unknown_meta = game.rules["unknown_card"]
    for key, f in fichas.items():
        if key in cards:
            continue
        # Carta nueva (no está en cards.yaml): roles desde la ficha; meta por defecto (las batallas lo ajustan).
        entry = stats["cards"][f.name]
        champion = str(entry["attributes"].get("Rarity", "")).lower() == "champion"
        cards[key] = CardInfo(f.name, f.name, f.variables["coste"], derived_roles(f, rules),
                              unknown_meta["sens"], unknown_meta["meta"],
                              game.rules["evo_bonus_default"] if "evolution" in entry else 0.0, champion)

    synergies = list(game.synergies) + _pair_synergies(fichas, rules)
    return replace(game, cards=cards, synergies=synergies, interactions=_breakpoints(stats, fichas, rules),
                   needs=_need_maps(fichas, rules), threats=_threat_maps(fichas, rules), fichas=fichas,
                   engine="atributos")


def deck_points(deck: list[str], evos: list[str], game: GameData) -> dict[str, float]:
    """Puntos del mazo por tipo: suma de las fichas (las cartas en espacio de evolución usan su ficha evolucionada)."""
    if not game.fichas:
        return {}
    total: dict[str, float] = {}
    for c in deck:
        f = game.fichas.get(norm(c))
        if not f:
            continue
        pts = f.evolution if (c in evos and f.evolution) else f.points
        for k, v in pts.items():
            total[k] = total.get(k, 0.0) + v
    return {k: round(v, 1) for k, v in total.items()}


def point_names(rules: dict | None = None) -> dict[str, str]:
    rules = rules if rules is not None else load_rules()
    return {k: p["name"] for k, p in rules["points"].items()}

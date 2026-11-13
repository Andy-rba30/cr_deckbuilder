"""Cómo se complementan las cartas (data/needs.yaml): necesidades de cada carta y quién las cubre.

Ejemplo: el Montapuercos necesita que alguien quite los edificios que lo frenan; el Terremoto lo
cubre. Una carta "exigente" vale menos sola y más bien acompañada: cada necesidad suma desde
−50% (nada la cubre) hasta +50% (cubierta del todo) de weight × necesidad.
"""
from __future__ import annotations

from .catalog import GameData, norm
from .collection import Player


def profiles(game: GameData, player: Player) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """(necesidades {carta: {necesidad: 0..1}}, coberturas {necesidad: {carta: 0..1}}) para tus cartas."""
    needs: dict[str, dict[str, float]] = {}
    provides: dict[str, dict[str, float]] = {}
    for key, n in game.needs.get("needs", {}).items():
        cards = {norm(c): float(v) for c, v in (n.get("cards") or {}).items()}
        provs = {norm(c): float(v) for c, v in (n.get("providers") or {}).items()}
        croles, proles = n.get("card_roles") or {}, n.get("provider_roles") or {}
        provides[key] = {}
        for name, c in player.cards.items():
            k = norm(name)
            a = cards.get(k)
            if a is None:
                a = max((float(croles.get(r, 0.0)) for r in c.roles), default=0.0)
            if a > 0:
                needs.setdefault(name, {})[key] = a
            p = provs.get(k)
            if p is None:
                p = max((float(proles.get(r, 0.0)) for r in c.roles), default=0.0)
            if p > 0:
                provides[key][name] = p
    return needs, provides


def complements(deck: list[str], game: GameData, prof) -> list[dict]:
    """Por cada necesidad de cada carta del mazo: cobertura 0..1 y qué cartas la cubren."""
    needs, provides = prof
    dset, out = set(deck), []
    for c in deck:
        for key, amount in needs.get(c, {}).items():
            cfg = game.needs["needs"][key]
            by = sorted(((p, v) for p, v in provides.get(key, {}).items() if p in dset and p != c),
                        key=lambda pv: -pv[1])
            cov = min(1.0, sum(v for _, v in by) / float(cfg.get("need", 1.0)))
            out.append({"card": c, "key": key, "name": cfg["name"], "amount": amount, "cov": cov, "by": by})
    return out


def complement_score(items: list[dict], weight: float) -> float:
    return weight * sum(i["amount"] * (i["cov"] - 0.5) for i in items)


def explain(items: list[dict], game: GameData, es, warn_below: float) -> tuple[list[tuple], list[tuple]]:
    """(lo que funciona, lo que falta) como [(texto, peso, detalle)], de lo más a lo menos importante."""
    good, bad = [], []
    for i in sorted(items, key=lambda i: -i["amount"]):
        cfg = game.needs["needs"][i["key"]]
        if i["by"] and i["cov"] >= 0.5:
            # Una carta en la frase (el verbo va en singular); las demás, en el detalle.
            others = ", ".join(es(p) for p, _ in i["by"][1:3])
            good.append((cfg["good"].format(p=es(i["by"][0][0]), c=es(i["card"])), i["amount"] * i["cov"],
                         f"{i['name']}: {i['cov']:.0%} cubierto" + (f" (también {others})" if others else "")))
        elif i["amount"] >= 0.5 and i["cov"] < warn_below:
            bad.append((cfg["bad"].format(c=es(i["card"])), i["amount"] * (1 - i["cov"]),
                        f"{i['name']}: {i['cov']:.0%} cubierto"))
    return sorted(good, key=lambda g: -g[1]), sorted(bad, key=lambda b: -b[1])

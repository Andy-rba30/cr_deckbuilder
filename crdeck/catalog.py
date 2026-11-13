"""Carga de datos estáticos: catálogo de cartas, sinergias, puntos de quiebre, reglas y arquetipos."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def norm(name: str) -> str:
    """Normaliza nombres: 'P.E.K.K.A' -> 'pekka', 'X-Bow' -> 'xbow'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass
class CardInfo:
    name: str
    es: str
    elixir: float
    roles: frozenset
    sens: float
    meta: float
    evo_bonus: float = 0.0
    champion: bool = False


@dataclass
class Synergy:
    a: str
    b: str
    weight: float
    reason: str
    source: str = "catálogo"   # "catálogo" (synergies.yaml), "batallas" o "ambos"


@dataclass
class Interaction:
    attacker: str
    target: str
    k: int
    verified: bool


@dataclass
class GameData:
    cards: dict[str, CardInfo]            # clave: nombre normalizado
    synergies: list[Synergy]
    interactions: list[Interaction]
    rules: dict
    archetypes: dict
    unknown_meta: dict[str, float] = field(default_factory=dict)  # meta de cartas que no están en cards.yaml
    battle_meta: object = None                                     # BattleMeta si se aplicaron batallas reales
    meta_detail: dict[str, dict] = field(default_factory=dict)     # nombre -> meta del catálogo, de datos y final
    threats: dict = field(default_factory=dict)                    # data/threats.yaml
    needs: dict = field(default_factory=dict)                      # data/needs.yaml
    fichas: dict = field(default_factory=dict)                     # motor v4: fichas de puntos por carta
    engine: str = "clasico"                                        # "clasico" (v3) o "atributos" (v4)

    def info(self, name: str) -> CardInfo | None:
        return self.cards.get(norm(name))


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_game_data(data_dir: Path = DATA_DIR) -> GameData:
    raw_cards = _load(data_dir / "cards.yaml")["cards"]
    cards = {}
    for c in raw_cards:
        cards[norm(c["name"])] = CardInfo(
            name=c["name"],
            es=c.get("es", c["name"]),
            elixir=float(c["elixir"]),
            roles=frozenset(c.get("roles", [])),
            sens=float(c.get("sens", 0.5)),
            meta=float(c.get("meta", 0.4)),
            evo_bonus=float(c.get("evo", 0.0)),
            champion=bool(c.get("champion", False)),
        )
    syn = [
        Synergy(s["cards"][0], s["cards"][1], float(s["weight"]), s.get("reason", ""))
        for s in _load(data_dir / "synergies.yaml")["synergies"]
    ]
    inter = [
        Interaction(i["attacker"], i["target"], int(i["kills_when_diff_ge"]), bool(i.get("verified", False)))
        for i in _load(data_dir / "interactions.yaml")["interactions"]
    ]
    rules = _load(data_dir / "rules.yaml")
    archetypes = _load(data_dir / "archetypes.yaml")["archetypes"]
    opt = lambda f: _load(data_dir / f) if (data_dir / f).exists() else {}
    return GameData(cards, syn, inter, rules, archetypes, threats=opt("threats.yaml"), needs=opt("needs.yaml"))

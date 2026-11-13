"""Convierte la respuesta de la API en la colección del jugador con niveles normalizados."""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import CardInfo, GameData


@dataclass
class OwnedCard:
    name: str
    id: int | None
    level: int                 # nivel en la escala del juego (normalizado)
    max_level: int             # nivel máximo del juego
    rarity: str
    elixir: float
    evo_unlocked: bool
    champion: bool
    icon: str | None
    icon_evo: str | None
    info: CardInfo | None      # None = carta que aún no está en cards.yaml

    @property
    def es(self) -> str:
        return self.info.es if self.info else self.name

    @property
    def roles(self) -> frozenset:
        return self.info.roles if self.info else frozenset()


@dataclass
class Player:
    tag: str
    name: str
    exp_level: int | None
    trophies: int | None
    max_level: int
    cards: dict[str, OwnedCard]   # clave: nombre en inglés de la API

    @property
    def unknown_cards(self) -> list[str]:
        return sorted(n for n, c in self.cards.items() if c.info is None)


def parse_player(raw: dict, game: GameData) -> Player:
    raw_cards = raw.get("cards", [])
    if not raw_cards:
        raise ValueError("La respuesta no contiene cartas.")
    # Las comunes tienen el maxLevel más alto: ese es el nivel máximo del juego.
    game_max = max(int(c.get("maxLevel", 0)) for c in raw_cards)

    cards = {}
    for c in raw_cards:
        name = c["name"]
        info = game.info(name)
        rarity = str(c.get("rarity", "")).lower()
        # La API entrega el nivel relativo a la rareza (una legendaria empieza en 1).
        level = int(c.get("level", 1)) + (game_max - int(c.get("maxLevel", game_max)))
        icons = c.get("iconUrls", {}) or {}
        elixir = c.get("elixirCost")
        cards[name] = OwnedCard(
            name=name,
            id=c.get("id"),
            level=level,
            max_level=game_max,
            rarity=rarity,
            elixir=float(elixir) if elixir is not None else (info.elixir if info else 4.0),
            evo_unlocked=int(c.get("evolutionLevel", 0) or 0) >= 1,
            champion=(rarity == "champion") or bool(info and info.champion),
            icon=icons.get("medium"),
            icon_evo=icons.get("evolutionMedium"),
            info=info,
        )
    return Player(
        tag=raw.get("tag", "?"),
        name=raw.get("name", "?"),
        exp_level=raw.get("expLevel"),
        trophies=raw.get("trophies"),
        max_level=game_max,
        cards=cards,
    )


def default_reference_level(player: Player, top_n: int = 24) -> int:
    """Nivel de referencia por defecto: la mediana de tus mejores `top_n` cartas."""
    levels = sorted((c.level for c in player.cards.values()), reverse=True)[:top_n]
    return levels[len(levels) // 2] if levels else player.max_level

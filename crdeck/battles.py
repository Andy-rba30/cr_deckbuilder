"""Batallas reales: descarga del historial (battlelog) rastreando rivales, y archivo local de batallas.

Se parte de tu tag, se leen tus últimas batallas, luego las de tus rivales, las de los rivales
de ellos, etc. Como el emparejamiento junta jugadores parecidos, la muestra refleja el meta
de tu nivel. Cada batalla se guarda una sola vez aunque aparezca en el historial de los dos.
"""
from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import api
from .catalog import DATA_DIR

BATTLES_PATH = DATA_DIR / "battles.json"
ISO = "%Y-%m-%dT%H:%M:%SZ"


def parse_battle(raw: dict, battle_types) -> dict | None:
    """Convierte una batalla de la API al formato compacto; None si no sirve (2v2, otro modo...)."""
    if raw.get("type") not in battle_types:
        return None
    team, opp = raw.get("team") or [], raw.get("opponent") or []
    if len(team) != 1 or len(opp) != 1:
        return None
    decks = []
    for p in (team[0], opp[0]):
        cards = p.get("cards") or []
        if len(cards) != 8 or not p.get("tag"):
            return None
        decks.append({"tag": p["tag"],
                      "cards": [[c["name"], int(c.get("level", 1)), c.get("maxLevel")] for c in cards]})
    try:
        t = datetime.strptime(raw["battleTime"], "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    a, b = int(team[0].get("crowns") or 0), int(opp[0].get("crowns") or 0)
    return {
        "key": raw["battleTime"] + "|" + "|".join(sorted(d["tag"] for d in decks)),
        "time": t.strftime(ISO),
        "type": raw["type"],
        "decks": decks,
        "winner": 0 if a > b else 1 if b > a else None,   # None = empate
    }


def crawl(seed_tags: list[str], max_players: int = 100, battle_types=("PvP", "pathOfLegend"),
          fetch: Callable[[str], list[dict]] | None = None, delay: float = 0.05,
          progress: Callable[[int, int, int], None] | None = None) -> tuple[list[dict], dict]:
    """Recorre historiales empezando por `seed_tags`. Devuelve (batallas, resumen)."""
    fetch = fetch or api.fetch_battlelog
    queue, seen = deque(), set()
    for t in seed_tags:
        tag = "#" + api.normalize_tag(t)
        if tag not in seen:
            seen.add(tag)
            queue.append(tag)

    battles: dict[str, dict] = {}
    cards_info: dict[str, dict] = {}
    visited = errors = streak = 0
    while queue and visited < max_players:
        tag = queue.popleft()
        try:
            log = fetch(tag)
            streak = 0
        except api.ApiError as e:
            if e.fatal:
                raise
            errors += 1
            streak += 1
            if streak >= 5:
                raise api.ApiError(f"Se detuvo la descarga tras 5 errores seguidos. Último: {e}") from e
            continue
        visited += 1
        for raw in log:
            b = parse_battle(raw, battle_types)
            if b is None:
                continue
            battles.setdefault(b["key"], b)
            for side in ("team", "opponent"):
                for c in raw[side][0]["cards"]:
                    cards_info.setdefault(c["name"], card_info(c))
            for d in b["decks"]:
                if d["tag"] not in seen:
                    seen.add(d["tag"])
                    queue.append(d["tag"])
        if progress:
            progress(visited, max_players, len(battles))
        if delay:
            time.sleep(delay)
    return list(battles.values()), {"players": visited, "errors": errors, "cards": cards_info}


def card_info(c: dict) -> dict:
    """Datos para dibujar una carta que quizá no tienes: imagen, rareza y elixir."""
    return {"icon": (c.get("iconUrls") or {}).get("medium"), "rarity": str(c.get("rarity", "")).lower(),
            "elixir": c.get("elixirCost")}


def recent(battles: list[dict], max_age_days: float | None, now: datetime | None = None) -> list[dict]:
    if not max_age_days:
        return battles
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=max_age_days)).strftime(ISO)
    return [b for b in battles if b["time"] >= cutoff]   # fechas ISO: se comparan como texto


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_battles(path: Path = BATTLES_PATH) -> list[dict]:
    return _load(path).get("battles", [])


def load_cards_info(path: Path = BATTLES_PATH) -> dict[str, dict]:
    return _load(path).get("cards", {})


def save_battles(new: list[dict], path: Path = BATTLES_PATH, max_age_days: float | None = None,
                 now: datetime | None = None, cards_info: dict | None = None) -> int:
    """Une las batallas nuevas con las guardadas (sin repetir), descarta las viejas y guarda. Devuelve el total."""
    merged = {b["key"]: b for b in load_battles(path)}
    merged.update({b["key"]: b for b in new})
    battles = sorted(recent(list(merged.values()), max_age_days, now), key=lambda b: b["time"])
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = {**load_cards_info(path), **(cards_info or {})}
    payload = {"version": 1, "updated": (now or datetime.now(timezone.utc)).strftime(ISO),
               "cards": cards, "battles": battles}
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(battles)

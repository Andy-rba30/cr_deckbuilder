"""Punto de entrada común: carga el jugador desde la API, un JSON o la demo."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .api import fetch_player
from .catalog import DATA_DIR, GameData, load_game_data
from .collection import Player, parse_player


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_PATH) -> bool:
    """Lector mínimo de .env. Se vuelve a leer en cada uso, así un cambio en .env
    se aplica sin reiniciar Streamlit. Devuelve False si el archivo no existe."""
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
    return True


def load_player(game: GameData, tag: str | None = None, json_path: str | None = None,
                demo: bool = False) -> Player:
    if demo:
        raw = json.loads((DATA_DIR / "demo_player.json").read_text(encoding="utf-8"))
    elif json_path:
        raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
    elif tag:
        raw = fetch_player(tag)
    else:
        raise ValueError("Indica un tag, un archivo JSON o el modo demo.")
    return parse_player(raw, game)


__all__ = ["load_env", "load_player", "load_game_data"]

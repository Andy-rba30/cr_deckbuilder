"""Stats de las cartas desde la wiki de Clash Royale (clashroyale.fandom.com), vía su API MediaWiki.

Por cada carta se leen las tablas de la página (atributos y stats a nivel 11), y si existen las de
su evolución (`Carta/Evolution`) y su versión héroe (`Carta/Hero`). Se guardan en data/card_stats.json
solo los datos (números y palabras clave), no los textos de la wiki.

Fuente: Clash Royale Wiki (Fandom), contenido bajo licencia CC BY-SA. Los stats pueden ir unos días
por detrás de un cambio de balance: vuelve a ejecutar `python cli.py --mode wiki` cuando haya uno.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from bs4 import BeautifulSoup

from .catalog import DATA_DIR

WIKI_API = "https://clashroyale.fandom.com/api.php"
WIKI_PAGE = "https://clashroyale.fandom.com/wiki/"
STATS_PATH = DATA_DIR / "card_stats.json"
HEADERS = {"User-Agent": "cr-deckbuilder (uso personal; lee stats de cartas)"}
ATTRIBUTE_HINTS = {"Cost", "Hit Speed", "Target", "Type", "Rarity", "Range", "Speed", "Radius", "Lifetime",
                   "Count", "Transport", "Deploy Time"}
# Expresión (en la introducción de la página o en los nombres de columnas) -> habilidad.
ABILITY_PATTERNS = {
    r"\bstun": "stun", r"\bslow(s|ed|ing|down)\b": "slow", r"\bfreez": "freeze",
    r"knock(s|ing)? ?back|push(es)? back|pushback": "knockback", r"spawn speed|summon": "spawner",
    r"\bcharg(e|es|ing)\b": "charge", r"\bdash": "dash", r"\bjump": "jump", r"\bshield": "shield",
    r"\bheal": "heal", r"\brage\b": "rage", r"\bpull|\bdrag": "pull", r"death damage": "death_damage",
    r"\bchain(?!\s?mail)": "chain", r"invisib|cloak": "invisible", r"\btaunt": "taunt", r"\breset": "reset",
    r"\bparr(y|ies)|\bblock the attack": "parry", r"less damage|damage reduction": "damage_reduction",
    r"\bramp": "ramp", r"\btunnel|\bburrow|underground": "tunnel", r"\broot": "root",
}


class WikiError(Exception):
    pass


def _num(text: str):
    """'1,779' -> 1779 · '1.6 sec' -> 1.6 · 'Very Fast (120)' -> 120 · 'x3' -> 3 · si no, el texto."""
    t = text.replace(",", "").strip()
    m = re.search(r"\(([\d.]+)\)", t)            # "Very Fast (120)", "Melee: Short (0.8)"
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"x?\s*([\d.]+)\s*(sec|tiles|%)?", t)
    if m:
        return float(m.group(1))
    return t


def _cells(row) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]


def parse_page(html: str) -> dict:
    """Atributos (tabla principal), tablas secundarias (otra tropa, habilidad, evolución) y stats a nivel 11."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"attributes": {}, "secondary": [], "stats": {}, "abilities": []}
    for t in soup.find_all("table", class_="wikitable"):
        rows = t.find_all("tr")
        if len(rows) < 2:
            continue
        head = _cells(rows[0])
        tid = t.get("id") or ""
        if head and head[0] == "Level":
            row = next((_cells(r) for r in rows[1:] if _cells(r)[:1] == ["11"]), None)
            if row is None:
                row = _cells(rows[-1])       # sin nivel 11: la última fila
            for h, v in zip(head[1:], row[1:]):
                out["stats"].setdefault(h, _num(v))
        elif tid.startswith("unit-attributes-table") or (set(head) & ATTRIBUTE_HINTS and "Objective" not in head):
            values = {h: _num(v) for h, v in zip(head, _cells(rows[1])) if h}
            section = t.find_previous(["h2", "h3", "h4"])
            name = section.get_text(" ", strip=True) if section else ""
            if tid == "unit-attributes-table" or (not out["attributes"] and "Cost" in values):
                for k, v in values.items():
                    out["attributes"].setdefault(k, v)
            else:
                out["secondary"].append({"section": name, **values})
    # Habilidades: nombres de columnas + introducción de la página, sin la descripción de su aspecto
    # ("appears as..."). Solo se guardan las palabras clave, no el texto.
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    intro = next((p for p in paras if len(p) > 80), "").lower()
    intro = re.split(r"\bappears? as\b|takes the appearance|\bappearance\b", intro)[0]
    columns = " ".join(list(out["attributes"]) + [k for s in out["secondary"] for k in s] + list(out["stats"])).lower()
    out["abilities"] = sorted({a for pat, a in ABILITY_PATTERNS.items() if re.search(pat, intro + " | " + columns)})
    return out


def fetch_page(title: str, client: httpx.Client) -> dict | None:
    """Página ya interpretada, o None si no existe."""
    params = {"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": 2,
              "redirects": 1}
    for attempt in range(3):
        try:
            r = client.get(WIKI_API, params=params, timeout=30)
        except httpx.HTTPError as e:
            if attempt == 2:
                raise WikiError(f"No se pudo contactar la wiki: {e}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return None
        parsed = parse_page(data["parse"]["text"])
        parsed["title"] = data["parse"].get("title", title)
        return parsed if parsed["attributes"] or parsed["stats"] else None
    raise WikiError("La wiki respondió 429 (demasiadas peticiones) varias veces seguidas.")


def _titles(name: str) -> list[str]:
    """La wiki a veces pone un punto final (Mini P.E.K.K.A.)."""
    return [name, name + "."] if name.endswith("A") and "." in name else [name]


def fetch_all(names: list[str], delay: float = 0.3, progress: Callable[[int, int, str], None] | None = None,
              client: httpx.Client | None = None) -> dict:
    """Descarga carta, evolución y héroe de cada nombre. Devuelve el contenido de card_stats.json."""
    own = client is None
    client = client or httpx.Client(headers=HEADERS, follow_redirects=True)
    cards, missing = {}, []
    try:
        for i, name in enumerate(names, 1):
            entry = None
            for title in _titles(name):
                entry = fetch_page(title, client)
                time.sleep(delay)
                if entry:
                    base = entry["title"]
                    for kind in ("Evolution", "Hero"):
                        extra = fetch_page(f"{base}/{kind}", client)
                        time.sleep(delay)
                        if extra:
                            entry[kind.lower()] = extra
                    break
            if entry:
                entry["url"] = WIKI_PAGE + entry["title"].replace(" ", "_")
                cards[name] = entry
            else:
                missing.append(name)
            if progress:
                progress(i, len(names), name)
    finally:
        if own:
            client.close()
    return {"source": "Clash Royale Wiki (clashroyale.fandom.com), licencia CC BY-SA",
            "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": 11, "missing": missing, "cards": cards}


def load_stats(path: Path = STATS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_stats(data: dict, path: Path = STATS_PATH) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

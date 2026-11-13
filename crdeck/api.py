"""Cliente mínimo de la API oficial de Clash Royale, con caché en disco."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
VALID_TAG = re.compile(r"^[0289PYLQGRJCUV]{3,15}$")
PLACEHOLDERS = {"pega_aqui_tu_clave", "tu_clave", ""}


class ApiError(Exception):
    pass


def normalize_tag(tag: str) -> str:
    t = tag.strip().upper().replace("#", "").replace("O", "0")
    if not VALID_TAG.match(t):
        raise ApiError(f"Tag inválido: '{tag}'. Solo puede tener los caracteres 0289PYLQGRJCUV.")
    return t


def fetch_player(tag: str, api_key: str | None = None, base_url: str | None = None,
                 ttl_seconds: int = 600, use_cache: bool = True) -> dict:
    tag = normalize_tag(tag)
    api_key = api_key or os.getenv("CR_API_KEY")
    base_url = (base_url or os.getenv("CR_API_BASE") or "https://api.clashroyale.com/v1").rstrip("/")
    cache_file = CACHE_DIR / f"player_{tag}.json"

    if use_cache and cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl_seconds:
        return json.loads(cache_file.read_text(encoding="utf-8"))

    api_key = (api_key or "").strip()
    if api_key in PLACEHOLDERS:
        raise ApiError("No hay clave: en el archivo .env (carpeta del proyecto) CR_API_KEY sigue vacío "
                       "o con el texto de ejemplo. Pega tu clave y guarda el archivo.")

    url = f"{base_url}/players/%23{tag}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    last_err = None
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=headers, timeout=15)
        except httpx.HTTPError as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            data = r.json()
            CACHE_DIR.mkdir(exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 403:
            raise ApiError(_explain_403(r))
        msgs = {
            400: "Petición incorrecta (revisa el tag).",
            404: "No existe un jugador con ese tag.",
            503: "La API está en mantenimiento.",
        }
        raise ApiError(f"Error {r.status_code}: {msgs.get(r.status_code, r.text[:200])}")
    raise ApiError(f"No se pudo contactar la API: {last_err or 'demasiadas peticiones (429)'}")


def _explain_403(r: httpx.Response) -> str:
    """Supercell indica en el cuerpo del 403 si el problema es la clave o la IP."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    reason, message = body.get("reason", ""), body.get("message", "")
    if reason == "accessDenied.invalidIp":
        ip = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", message)
        seen = f" La API ve tu conexión con la IP {ip.group(1)}." if ip else ""
        return ("Error 403: tu clave no tiene registrada la IP desde la que te conectas." + seen +
                " Crea una clave nueva en developer.clashroyale.com con esa IP y pégala en .env.")
    if reason == "accessDenied":
        return ("Error 403: la clave no es válida. Revisa que la copiaste completa (es un texto muy largo), "
                "en una sola línea y sin espacios, y que no la borraste en el portal.")
    return f"Error 403: acceso denegado ({reason or 'sin motivo'}: {message[:200]})"

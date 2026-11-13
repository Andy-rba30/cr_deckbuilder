"""Piezas visuales en HTML para la app (cartas, mazos, medidores). No dependen de Streamlit."""
from __future__ import annotations

from html import escape

RARITY_COLOR = {
    "common": "#8fa3b8", "rare": "#f0a020", "epic": "#b05cff",
    "legendary": "#33c9c0", "champion": "#f5c518",
}
FAMILIAR_MIN = 0.3   # desde este uso se marca la carta con ♥ (la juegas seguido)
METER_COLOR = {
    "Ataque": "#ef6a3a", "Defensa": "#3b82f6", "Sinergia": "#22c55e", "Cobertura": "#a855f7",
}

CSS = """
<style>
.crd-root{--crd-panel:rgba(127,127,127,.07);--crd-border:rgba(127,127,127,.22);--crd-muted:rgba(127,127,127,.95);--crd-gold:#f5b301}
.crd-deck{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start;background:var(--crd-panel);
  border:1px solid var(--crd-border);border-radius:16px;padding:16px;margin:4px 0 6px}
.crd-head{flex-basis:100%;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.crd-title{font-weight:800;font-size:1.15rem}
.crd-sub{font-size:.8rem;color:var(--crd-muted)}
.crd-left{flex:0 1 400px;min-width:250px}
.crd-right{flex:1 1 250px;min-width:230px;display:flex;flex-direction:column;gap:8px}
.crd-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.crd-pool{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:10px}
.crd-tile{min-width:0}
.crd-card{position:relative;aspect-ratio:4/5;border-radius:11px;overflow:hidden;border:2px solid var(--rar);
  background:linear-gradient(160deg,var(--rar) 0%,#1a1f2b 78%)}
/* Las imágenes oficiales (285×420) traen margen transparente: se encuadra solo la carta (14–271 × 66–388). */
.crd-card img{position:absolute;left:-5.45%;top:0;margin-top:-25.7%;width:110.9%;max-width:none;height:auto;display:block}
.crd-card .ph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;
  font-weight:800;font-size:.78rem;line-height:1.1;padding:22px 5px 18px;color:#fff;text-shadow:0 1px 3px #000}
.crd-card.evo{border-color:#c86bff;box-shadow:0 0 0 2px #c86bff55,0 0 16px #b44dffaa}
.crd-card.empty{border:2px dashed var(--crd-border);background:var(--crd-panel)}
.crd-card.empty .ph{color:var(--crd-muted);text-shadow:none;font-weight:600}
.crd-elx{position:absolute;top:5px;left:5px;width:21px;height:21px;border-radius:50% 0 50% 50%;transform:rotate(-45deg);
  background:radial-gradient(circle at 35% 35%,#f6b8ff,#c21bd6 55%,#6d0a7a);box-shadow:0 1px 3px #000a;
  display:flex;align-items:center;justify-content:center}
.crd-elx span{transform:rotate(45deg);font-size:.72rem;font-weight:900;color:#fff;text-shadow:0 1px 1px #000}
.crd-badge{position:absolute;top:5px;right:5px;font-size:.58rem;font-weight:900;padding:1px 5px;border-radius:6px;letter-spacing:.03em}
.crd-badge.evo{background:#9b3cf0;color:#fff}
.crd-badge.champ{background:#f5c518;color:#2a1d00}
.crd-fam{position:absolute;bottom:21px;left:5px;width:17px;height:17px;border-radius:50%;background:#ec4899;color:#fff;
  font-size:.62rem;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px #000a}
.crd-lv{position:absolute;bottom:0;left:0;right:0;text-align:center;font-size:.72rem;font-weight:800;padding:2px 0;
  background:rgba(0,0,0,.66);color:var(--lvc,#fff)}
.crd-name{font-size:.7rem;text-align:center;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crd-note{font-size:.66rem;text-align:center;color:var(--crd-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crd-foot{display:flex;align-items:center;gap:8px;margin-top:12px;flex-wrap:wrap}
.crd-pill{display:inline-flex;align-items:center;gap:6px;background:var(--crd-panel);border:1px solid var(--crd-border);
  padding:3px 10px;border-radius:999px;font-size:.82rem;font-weight:600}
.crd-drop{width:13px;height:13px;border-radius:50% 0 50% 50%;transform:rotate(-45deg);display:inline-block;
  background:radial-gradient(circle at 35% 35%,#f6b8ff,#c21bd6 55%,#6d0a7a)}
.crd-copy{background:var(--crd-gold);color:#1b1300 !important;font-weight:800;text-decoration:none !important;
  padding:5px 12px;border-radius:9px;font-size:.85rem}
.crd-score{font-size:1.7rem;font-weight:900;color:var(--crd-gold);line-height:1}
.crd-meter{background:var(--crd-panel);border:1px solid var(--crd-border);border-radius:10px;padding:7px 11px}
.crd-meter .lab{display:flex;justify-content:space-between;font-size:.82rem;font-weight:600}
.crd-bar{height:8px;background:rgba(127,127,127,.2);border-radius:6px;overflow:hidden;margin-top:5px}
.crd-bar i{display:block;height:100%;border-radius:6px}
.crd-chips{display:flex;flex-wrap:wrap;gap:6px}
.crd-chip{font-size:.75rem;padding:2px 9px;border-radius:999px;border:1px solid var(--crd-border)}
.crd-chip.good{border-color:#22c55e88;background:#22c55e1f}
.crd-chip.bad{border-color:#ef444488;background:#ef44441f}
.crd-chip.warn{border-color:#f59e0b88;background:#f59e0b1f}
.crd-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:6px 0 10px}
.crd-stat{background:var(--crd-panel);border:1px solid var(--crd-border);border-radius:12px;padding:10px 14px}
.crd-stat b{display:block;font-size:1.35rem;font-weight:900}
.crd-stat span{font-size:.78rem;color:var(--crd-muted)}
.crd-combo{display:flex;align-items:center;gap:8px;background:var(--crd-panel);border:1px solid var(--crd-border);
  border-radius:12px;padding:8px 10px}
.crd-combo .crd-tile{width:56px;flex:0 0 56px}
.crd-combo .crd-card .ph{font-size:.55rem;padding:16px 2px 4px}
.crd-combo .txt{font-size:.78rem;min-width:0}
.crd-combos{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
.crd-rank{display:flex;flex-wrap:wrap;align-items:center;gap:14px;background:var(--crd-panel);
  border:1px solid var(--crd-border);border-radius:14px;padding:10px 14px;margin-bottom:8px}
.crd-rank .info{flex:0 0 210px}
.crd-rank .mini{flex:1 1 380px;display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:5px;max-width:560px}
.crd-rank .mini .crd-card .ph{font-size:.52rem;padding:14px 2px 12px}
.crd-rank .mini .crd-lv{font-size:.58rem}
.crd-rank .mini .crd-elx{width:15px;height:15px;top:3px;left:3px}
.crd-rank .mini .crd-elx span{font-size:.55rem}
.crd-rank .mini .crd-badge{font-size:.5rem;padding:0 3px}
.crd-pos{font-size:1.4rem;font-weight:900;color:var(--crd-gold);margin-right:6px}
</style>
"""


def _e(s) -> str:
    return escape(str(s), quote=True)


def level_color(gap: int | None) -> str:
    """Verde si estás al nivel de referencia o más, ámbar 1 nivel abajo, rojo 2 o más."""
    if gap is None or gap <= 0:
        return "#4ade80"
    return "#fbbf24" if gap == 1 else "#f87171"


def card_tile(name: str, *, elixir: float | None = None, rarity: str = "", icon: str | None = None,
              level: int | None = None, gap: int | None = None, evo: bool = False, champion: bool = False,
              note: str = "", tooltip: str = "", show_name: bool = True, familiar: float = 0.0) -> str:
    rar = RARITY_COLOR.get(rarity, "#6b7280")
    show_name = show_name and bool(icon)   # sin imagen, el nombre ya va dentro de la ficha
    img = f'<img src="{_e(icon)}" alt="{_e(name)}" loading="lazy">' if icon else f'<div class="ph">{_e(name)}</div>'
    elx = f'<div class="crd-elx"><span>{elixir:g}</span></div>' if elixir is not None else ""
    badge = ('<div class="crd-badge evo">EVO</div>' if evo
             else '<div class="crd-badge champ">👑</div>' if champion else "")
    lv = f'<div class="crd-lv" style="--lvc:{level_color(gap)}">Nv {level}</div>' if level is not None else ""
    fam = '<div class="crd-fam">♥</div>' if familiar >= FAMILIAR_MIN else ""
    cls = "crd-card evo" if evo else "crd-card"
    return (f'<div class="crd-tile" title="{_e(tooltip or name)}"><div class="{cls}" style="--rar:{rar}">'
            f'{img}{elx}{badge}{fam}{lv}</div>'
            + (f'<div class="crd-name">{_e(name)}</div>' if show_name else "")
            + (f'<div class="crd-note">{_e(note)}</div>' if note else "") + "</div>")


def empty_tile(label: str = "vacío") -> str:
    return (f'<div class="crd-tile"><div class="crd-card empty"><div class="ph">{_e(label)}</div></div>'
            f'<div class="crd-name">&nbsp;</div></div>')


def owned_tile(name: str, player, evals=None, *, evo: bool = False, note: str = "", show_name: bool = True,
               icon_override: str | None = None) -> str:
    """Ficha de una carta de tu colección, con nivel coloreado según la referencia."""
    oc = player.cards[name]
    ev = evals.get(name) if evals else None
    icon = icon_override or ((oc.icon_evo or oc.icon) if evo else oc.icon)
    fam = player.comfort.get(name, 0.0)
    tip = f"{oc.es} · nivel {oc.level}"
    if ev:
        tip += f" · valor {ev.value:.2f} · factor de nivel {ev.level_factor:.2f}"
    if fam:
        tip += f" · la juegas en el {fam:.0%} de tus batallas"
    return card_tile(oc.es, elixir=oc.elixir, rarity=oc.rarity, icon=icon, level=oc.level,
                     gap=ev.gap if ev else None, evo=evo, champion=oc.champion, note=note, tooltip=tip,
                     show_name=show_name, familiar=fam)


def meter(label: str, value: float, color: str | None = None, maximum: float = 10.0, text: str | None = None) -> str:
    pct = max(0.0, min(100.0, 100.0 * value / maximum))
    color = color or METER_COLOR.get(label, "#3b82f6")
    return (f'<div class="crd-meter"><div class="lab"><span>{_e(label)}</span>'
            f'<span>{_e(text if text is not None else f"{value:.1f}")}</span></div>'
            f'<div class="crd-bar"><i style="width:{pct:.0f}%;background:linear-gradient(90deg,{color}aa,{color})"></i>'
            f"</div></div>")


def cycle_cost(elixirs: list[float]) -> float:
    """Costo de ciclo: lo que cuesta jugar tus 4 cartas más baratas para volver a la que quieres."""
    return sum(sorted(elixirs)[:4])


def deck_html(title: str, d: dict, player, evals, link: str | None = None, subtitle: str = "",
              empty_slots: int = 0) -> str:
    """Mazo completo: cuadrícula 4×2, elixir, ciclo, copiar y panel de medidores."""
    tiles = [owned_tile(n, player, evals, evo=n in d["evos"]) for n in d["cards"]]
    tiles += [empty_tile() for _ in range(empty_slots)]
    elix = [player.cards[n].elixir for n in d["cards"]]
    foot = (f'<span class="crd-pill"><span class="crd-drop"></span>{d["avg_elixir"]:.1f} medio</span>'
            + (f'<span class="crd-pill">🔄 ciclo {cycle_cost(elix):g}</span>' if len(elix) >= 4 else "")
            + (f'<a class="crd-copy" href="{_e(link)}" target="_blank">📋 Copiar al juego</a>' if link else ""))
    meters = (win_meter(d["win"]) if d.get("win") else "") + "".join(meter(k, v) for k, v in d["ratings"].items())
    return (f'<div class="crd-root"><div class="crd-deck">'
            f'<div class="crd-head"><div><div class="crd-title">{_e(title)}</div>'
            + (f'<div class="crd-sub">{_e(subtitle)}</div>' if subtitle else "")
            + f'</div><div style="text-align:right"><div class="crd-sub">puntaje</div>'
            f'<div class="crd-score">{d["score"]:.2f}</div></div></div>'
            f'<div class="crd-left"><div class="crd-grid">{"".join(tiles)}</div><div class="crd-foot">{foot}</div></div>'
            f'<div class="crd-right">{meters}</div></div></div>')


def win_color(p: float) -> str:
    return "#22c55e" if p >= 0.52 else "#f59e0b" if p >= 0.48 else "#ef4444"


def win_meter(win: tuple[float, float, float]) -> str:
    """Probabilidad estimada de ganar contra un rival típico de tu nivel, con su rango (90%)."""
    p, lo, hi = win
    return meter("Victoria estimada", 100 * p, win_color(p), maximum=100,
                 text=f"{p:.0%}  ({lo:.0%}–{hi:.0%})")


def coverage_chips(cov: list[dict], es) -> str:
    """Una etiqueta por amenaza: verde ≥80%, ámbar ≥50%, roja por debajo. es: nombre en español."""
    items = []
    for t in cov:
        cls = "good" if t["cov"] >= 0.8 else "warn" if t["cov"] >= 0.5 else "bad"
        who = ", ".join(f"{es(c)} {a:.1f}" for c, a in t["by"]) or "ninguna carta"
        items.append((f"{t['name']} {t['cov']:.0%}", cls, f"Ej.: {t['examples']}. Responden: {who}"))
    return chips(items)


def chips(items: list[tuple[str, str, str]]) -> str:
    """items: (texto, clase good|bad|warn|'', tooltip)."""
    return ('<div class="crd-root"><div class="crd-chips">'
            + "".join(f'<span class="crd-chip {c}" title="{_e(t)}">{_e(x)}</span>' for x, c, t in items)
            + "</div></div>")


def stats_row(items: list[tuple[str, str]]) -> str:
    """Fila de cifras grandes: (valor, etiqueta)."""
    return ('<div class="crd-root"><div class="crd-stats">'
            + "".join(f'<div class="crd-stat"><b>{_e(v)}</b><span>{_e(k)}</span></div>' for v, k in items)
            + "</div></div>")


def pool_html(tiles: list[str]) -> str:
    return f'<div class="crd-root"><div class="crd-pool">{"".join(tiles)}</div></div>'


def combo_html(tile_a: str, tile_b: str, title: str, detail: str, sep: str = "+") -> str:
    return (f'<div class="crd-combo">{tile_a}<b>{_e(sep)}</b>{tile_b}'
            f'<div class="txt"><b>{_e(title)}</b><br><span class="crd-sub">{_e(detail)}</span></div></div>')


def combos_html(items: list[str]) -> str:
    return f'<div class="crd-root"><div class="crd-combos">{"".join(items)}</div></div>'


def rank_row(pos: int, name: str, score: float, delta: float | None, elixir: float, tiles: list[str],
             pct: float, win: tuple | None = None) -> str:
    """Fila del ranking de arquetipos: puesto, nombre, barra de puntaje y mini mazo."""
    d = f" ({delta:+.2f} vs. óptimo)" if delta is not None else ""
    d += f" · {win[0]:.0%} victoria" if win else ""
    return (f'<div class="crd-root"><div class="crd-rank"><div class="info">'
            f'<div><span class="crd-pos">{pos}</span><b>{_e(name)}</b></div>'
            f'<div class="crd-sub">puntaje {score:.2f}{_e(d)} · elixir {elixir:.1f}</div>'
            f'<div class="crd-bar"><i style="width:{max(0, min(100, pct)):.0f}%;'
            f'background:linear-gradient(90deg,#f5b301aa,#f5b301)"></i></div></div>'
            f'<div class="mini">{"".join(tiles)}</div></div></div>')

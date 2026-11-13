"""Meta calculado con batallas reales.

* Fuerza de cada carta: regresión logística (Bradley-Terry) sobre quién ganó cada batalla,
  usando las cartas de los dos mazos y la diferencia de nivel medio. Así una carta no parece
  fuerte solo porque la juega gente con más nivel ni porque siempre va con otra carta fuerte.
* Sinergia de cada par: cuántas veces más se juegan juntas que si fuera al azar (lift) y,
  con mucha prudencia, cuánto más ganan juntas que por separado.
* Mezcla con el catálogo: cada carta pesa más del lado de los datos cuantas más partidas tiene;
  con pocas partidas manda cards.yaml. Las sinergias de datos se suman a las de synergies.yaml.

Todos los parámetros están en data/rules.yaml, sección battle_meta.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path

import numpy as np

from .battles import BATTLES_PATH, load_battles, recent
from .catalog import GameData, Synergy, norm


@dataclass
class CardStat:
    name: str
    games: int                 # mazos que la llevaban
    wins: int
    draws: int
    usage: float               # fracción de mazos que la llevan
    win_rate: float            # victorias / partidas (empate = media victoria)
    strength: float            # efecto en log-odds de llevarla (controlando nivel y compañeras)


@dataclass
class PairStat:
    a: str
    b: str
    together: int              # mazos con las dos cartas
    expected: float            # mazos esperados si se eligieran por separado
    win_rate: float | None     # win rate de los mazos con las dos (None si hay muy pocos)
    weight: float              # sinergia que aporta al modelo
    effect: float | None = None  # cuánto más ganan juntas de lo que predicen por separado (log-odds)

    @property
    def effect_points(self) -> float | None:
        """El efecto en puntos de probabilidad de ganar (0.05 = +5 puntos)."""
        return None if self.effect is None else 1.0 / (1.0 + math.exp(-self.effect)) - 0.5

    @property
    def lift(self) -> float:
        return self.together / self.expected if self.expected > 0 else float("inf")


@dataclass
class BattleMeta:
    n_battles: int
    n_decks: int
    n_players: int
    first: str                 # fecha de la batalla más antigua (ISO)
    last: str
    level_effect: float        # log-odds por cada nivel medio de ventaja
    cards: dict[str, CardStat]
    pairs: list[PairStat]      # los que superan min_weight, de mayor a menor |peso|
    # Para estimar la probabilidad de ganar de un mazo (ver win_probability):
    index: dict[str, int] = field(default_factory=dict, repr=False)   # carta -> columna de la regresión
    coef: np.ndarray | None = field(default=None, repr=False)        # cartas, pares y efecto de nivel (al final)
    cov: np.ndarray | None = field(default=None, repr=False)         # covarianza aproximada de coef
    mean_x: np.ndarray | None = field(default=None, repr=False)      # mazo medio del meta (uso de cartas y pares)
    pair_index: dict[tuple, int] = field(default_factory=dict, repr=False)  # par (ordenado) -> columna

    @property
    def level_win_gain(self) -> float:
        """Puntos de probabilidad de ganar que da 1 nivel medio de ventaja (0.05 = +5 puntos)."""
        return 1.0 / (1.0 + math.exp(-self.level_effect)) - 0.5

    def win_probability(self, deck: list[str], level_diff: float, z: float = 1.645) -> tuple[float, float, float]:
        """Probabilidad de ganar contra un rival típico del meta (mazo medio, al nivel de referencia).

        level_diff: nivel medio de tu mazo menos el de tus rivales. Devuelve (estimación, mínimo, máximo)
        con un intervalo del 90%. Las cartas sin datos cuentan como neutras.
        """
        v = np.append(-self.mean_x, level_diff)
        for c in deck:
            if c in self.index:
                v[self.index[c]] += 1.0
        for pair in combinations(sorted(set(deck)), 2):
            if pair in self.pair_index:
                v[self.pair_index[pair]] += 1.0
        logit = float(v @ self.coef)
        sd = math.sqrt(max(0.0, float(v @ self.cov @ v)))
        sig = lambda t: 1.0 / (1.0 + math.exp(-t))
        return sig(logit), sig(logit - z * sd), sig(logit + z * sd)


# ---------------------------------------------------------------- cálculo
def compute_meta(battles: list[dict], cfg: dict, now=None) -> BattleMeta | None:
    battles = recent(battles, cfg.get("max_age_days"), now)
    if not battles:
        return None

    # Niveles normalizados a la escala del juego (como en collection.parse_player).
    game_max = max((c[2] or 0 for b in battles for d in b["decks"] for c in d["cards"]), default=0)

    def deck_level(d) -> float:
        return sum(c[1] + ((game_max - c[2]) if c[2] else 0) for c in d["cards"]) / len(d["cards"])

    games, wins, draws = Counter(), Counter(), Counter()
    pair_n, pair_w = Counter(), Counter()
    rows, level_diffs, players = [], [], set()
    for b in battles:
        decks = [sorted({c[0] for c in d["cards"]}) for d in b["decks"]]
        for i, cards in enumerate(decks):
            players.add(b["decks"][i]["tag"])
            res = 0.5 if b["winner"] is None else float(b["winner"] == i)
            for c in cards:
                games[c] += 1
                wins[c] += res == 1.0
                draws[c] += res == 0.5
            for pair in combinations(cards, 2):
                pair_n[pair] += 1
                pair_w[pair] += res
        if b["winner"] is not None:
            w = b["winner"]
            rows.append((decks[w], decks[1 - w]))
            level_diffs.append(deck_level(b["decks"][w]) - deck_level(b["decks"][1 - w]))

    names = sorted(games)
    n_decks = 2 * len(battles)
    index = {n: i for i, n in enumerate(names)}
    # Pares con suficientes mazos juntos: se estima cuánto más ganan juntas (efecto de interacción).
    syn = cfg["synergy"]
    frequent = sorted((p for p, n in pair_n.items() if n >= syn["min_pair_games"]), key=lambda p: -pair_n[p])
    pair_index = {p: len(names) + i for i, p in enumerate(frequent[: syn["max_pair_effects"]])}
    coef, cov = _fit(rows, level_diffs, index, cfg["ridge"], pair_index, syn["pair_ridge"])
    strength, level_effect = coef[: len(names)], float(coef[-1])
    effects = {p: float(coef[i]) for p, i in pair_index.items()}

    cards = {}
    for i, n in enumerate(names):
        cards[n] = CardStat(n, games[n], int(wins[n]), int(draws[n]), games[n] / n_decks,
                            (wins[n] + 0.5 * draws[n]) / games[n], float(strength[i]))

    pairs = _pair_weights(names, games, pair_n, pair_w, effects, n_decks, syn)
    times = [b["time"] for b in battles]
    # Mazo medio: uso de cada carta y de cada par frecuente.
    mean_x = np.array([games[n] / n_decks for n in names] + [pair_n[p] / n_decks for p in pair_index])
    return BattleMeta(len(battles), n_decks, len(players), min(times), max(times),
                      level_effect, cards, pairs, index, coef, cov, mean_x, pair_index)


def _fit(rows, level_diffs, idx, ridge: float, pair_index: dict | None = None, pair_ridge: float = 25.0,
         iters: int = 50):
    """Regresión logística con regularización L2 (Newton). Cada fila: mazo del ganador − del perdedor.
    Columnas: cartas, pares frecuentes (ambas cartas en el mazo) y diferencia de nivel (al final).
    Devuelve (coeficientes, covarianza aproximada)."""
    pair_index = pair_index or {}
    k = len(idx) + len(pair_index)
    lam = np.full(k + 1, float(ridge))
    lam[len(idx):k] = float(pair_ridge)   # los pares, con más prudencia: hay menos datos de cada uno
    lam[k] = 1e-3                         # el efecto del nivel casi no se regulariza
    if not rows:
        return np.zeros(k + 1), np.diag(1.0 / lam)
    X = np.zeros((len(rows), k + 1))
    for r, (win, lose) in enumerate(rows):
        for sign, deck in ((1.0, win), (-1.0, lose)):
            for c in deck:
                X[r, idx[c]] += sign
            if pair_index:
                for pair in combinations(deck, 2):   # los mazos llegan ordenados
                    col = pair_index.get(pair)
                    if col is not None:
                        X[r, col] += sign
        X[r, k] = level_diffs[r]
    w = np.zeros(k + 1)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(X @ w)))
        grad = -X.T @ (1.0 - p) + lam * w
        hess = (X.T * (p * (1.0 - p))) @ X + np.diag(lam)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    p = 1.0 / (1.0 + np.exp(-(X @ w)))
    hess = (X.T * (p * (1.0 - p))) @ X + np.diag(lam)
    return w, np.linalg.inv(hess)      # aproximación de Laplace: covarianza = inversa del hessiano


def _pair_weights(names, games, pair_n, pair_w, effects, n_decks, cfg) -> list[PairStat]:
    """Peso de cada par = efecto aprendido (ganan más juntas) + un poco de "se juegan juntas"."""
    s, lo, hi = cfg["smoothing"], cfg["clip"][0], cfg["clip"][1]
    candidates = [n for n in names if games[n] >= cfg["min_together"]]   # cartas casi nunca vistas: sin datos de pares
    out = []
    for a, b in combinations(candidates, 2):
        n = pair_n.get((a, b), 0)
        expected = games[a] * games[b] / n_decks
        effect = effects.get((a, b))
        weight = cfg["cooc_scale"] * math.log2((n + s) / (expected + s))
        if effect is not None:
            weight += cfg["effect_scale"] * effect
        weight = min(hi, max(lo, weight))
        wr = pair_w[a, b] / n if n >= cfg["min_together"] else None
        if abs(weight) >= cfg["min_weight"]:
            out.append(PairStat(a, b, n, expected, wr, weight, effect))
    # Mitad del cupo para combos y mitad para "casi nunca juntas": los negativos tienen pesos
    # más grandes (log de cocientes pequeños) y si no, se llevarían todo el cupo.
    out.sort(key=lambda p: -abs(p.weight))
    pos, neg = [p for p in out if p.weight > 0], [p for p in out if p.weight < 0]
    half = cfg["max_pairs"] // 2
    chosen = pos[:half] + neg[:half]
    rest = pos[half:] + neg[half:]
    rest.sort(key=lambda p: -abs(p.weight))
    chosen += rest[: max(0, cfg["max_pairs"] - len(chosen))]
    chosen.sort(key=lambda p: -abs(p.weight))
    return chosen


# ---------------------------------------------------------------- aplicar al catálogo
def _percentiles(values: list[float]) -> np.ndarray:
    if len(values) == 1:
        return np.array([0.5])
    ranks = np.argsort(np.argsort(values, kind="stable"), kind="stable")
    return ranks / (len(values) - 1)


def pair_reason(p: PairStat) -> str:
    if p.effect is not None and abs(p.effect_points) >= 0.01:
        verb = "ganan" if p.effect > 0 else "pierden"
        return (f"Juntas {verb} {abs(p.effect_points) * 100:.0f} puntos más de lo que predice cada una "
                f"por separado ({p.together} mazos)")
    if p.weight >= 0:
        wr = f", {p.win_rate:.0%} de victorias" if p.win_rate is not None else ""
        return f"Se juegan juntas {p.lift:.1f}× más de lo esperado ({p.together} mazos{wr})"
    return f"Casi nunca van juntas ({p.together} mazos de {p.expected:.0f} esperados)"


def apply_meta(game: GameData, bm: BattleMeta, cfg: dict) -> GameData:
    """Devuelve una copia del catálogo con el meta y las sinergias ajustados por las batallas."""
    names = list(bm.cards)
    p = cfg["popularity_weight"]
    score = ((1 - p) * _percentiles([bm.cards[n].strength for n in names])
             + p * _percentiles([bm.cards[n].usage for n in names]))
    # Los datos deciden el ORDEN de las cartas; la escala sale de cards.yaml para no
    # desbalancear el valor de las cartas frente a sinergias y roles.
    scale = sorted(c.meta for c in game.cards.values())

    cards, unknown_meta, detail = dict(game.cards), {}, {}
    for n, sc in zip(names, score):
        st = bm.cards[n]
        data_meta = float(np.quantile(scale, sc))
        conf = st.games / (st.games + cfg["prior_games"])
        key = norm(n)
        info = cards.get(key)
        prior = info.meta if info else game.rules["unknown_card"]["meta"]
        final = conf * data_meta + (1 - conf) * prior
        if info:
            cards[key] = replace(info, meta=final)
        else:
            unknown_meta[key] = final
        detail[n] = {"catalogo": prior, "datos": data_meta, "final": final, "peso_datos": conf}

    data = {tuple(sorted((norm(pp.a), norm(pp.b)))): pp for pp in bm.pairs}
    synergies = []
    for s in game.synergies:
        pp = data.pop(tuple(sorted((norm(s.a), norm(s.b)))), None)
        if pp:
            synergies.append(Synergy(s.a, s.b, s.weight + pp.weight, f"{s.reason} · {pair_reason(pp)}", "ambos"))
        else:
            synergies.append(s)
    synergies += [Synergy(pp.a, pp.b, pp.weight, pair_reason(pp), "batallas") for pp in data.values()]

    return replace(game, cards=cards, synergies=synergies, unknown_meta=unknown_meta,
                   battle_meta=bm, meta_detail=detail)


def load_battle_meta(game: GameData, path: Path = BATTLES_PATH, now=None) -> tuple[GameData, BattleMeta | None]:
    """Catálogo con el meta de data/battles.json aplicado (o el catálogo tal cual si no hay datos)."""
    cfg = game.rules["battle_meta"]
    bm = compute_meta(load_battles(path), cfg, now)
    return (apply_meta(game, bm, cfg), bm) if bm else (game, None)

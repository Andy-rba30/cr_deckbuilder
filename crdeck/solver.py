"""Modelo ILP (OR-Tools CP-SAT) para armar 1 mazo o los 4 mazos de Guerra de Clanes."""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .catalog import GameData, norm
from .collection import Player
from .scoring import CardEval, evaluate_deck, synergy_index

SCALE = 1000  # CP-SAT solo trabaja con enteros


@dataclass
class SolveRequest:
    n_decks: int = 1
    war_unique: bool = False                   # Guerra: ninguna carta se repite entre mazos
    archetypes: list[str | None] = field(default_factory=list)   # un arquetipo (o None) por mazo
    locked: list[str] = field(default_factory=list)              # cartas obligatorias
    banned: list[str] = field(default_factory=list)              # cartas prohibidas
    exclude_decks: list[list[str]] = field(default_factory=list) # mazos ya mostrados (para alternativas)
    balance_weight: int = 10                   # Guerra: peso del mazo más débil
    time_limit: float = 20.0


@dataclass
class SolveResult:
    ok: bool
    status: str
    decks: list[dict]
    notes: list[str]


def _resolve(names, player: Player) -> list[str]:
    by_norm = {norm(n): n for n in player.cards}
    return [by_norm[norm(x)] for x in names if norm(x) in by_norm]


def solve(player: Player, game: GameData, evals: dict[str, CardEval], req: SolveRequest) -> SolveResult:
    rules = game.rules["deck"]
    m = cp_model.CpModel()
    notes: list[str] = []
    ids = list(player.cards)
    D = range(req.n_decks)
    archs = (req.archetypes + [None] * req.n_decks)[: req.n_decks]

    x = {(c, d): m.NewBoolVar(f"x[{c}][{d}]") for c in ids for d in D}
    e = {(c, d): m.NewBoolVar(f"e[{c}][{d}]") for c in ids if player.cards[c].evo_unlocked for d in D}

    if req.war_unique:
        for c in ids:
            m.Add(sum(x[c, d] for d in D) <= 1)

    for c in _resolve(req.banned, player):
        for d in D:
            m.Add(x[c, d] == 0)
    for c in _resolve(req.locked, player):
        if req.n_decks == 1:
            m.Add(x[c, 0] == 1)
        else:
            m.Add(sum(x[c, d] for d in D) >= 1)

    def has_role(c, roles):
        return bool(player.cards[c].roles & set(roles))

    syn = synergy_index(game, set(ids))
    deck_scores = []

    for d in D:
        X = lambda cs: sum(x[c, d] for c in cs)
        m.Add(X(ids) == rules["size"])

        arch = game.archetypes.get(archs[d]) if archs[d] else None
        role_limits = {**rules["role_limits"], **((arch or {}).get("role_limits", {}))}
        for role, lim in role_limits.items():
            group = [c for c in ids if role in player.cards[c].roles]
            if "min" in lim:
                m.Add(X(group) >= lim["min"])
            if "max" in lim:
                m.Add(X(group) <= lim["max"])
        spells = [c for c in ids if has_role(c, rules["spell_roles"])]
        m.Add(X(spells) >= rules["min_spells"])
        m.Add(X(spells) <= rules["max_spells"])
        m.Add(X([c for c in ids if player.cards[c].champion]) <= rules["max_champions"])

        lo, hi = rules["avg_elixir"]
        if arch:
            lo, hi = arch.get("avg_elixir", [lo, hi])
            label = f"Mazo {d + 1} ({arch['name']})"
            core = arch.get("core", [])
            owned_core = _resolve(core, player)
            if len(owned_core) < len(core):
                return SolveResult(False, "SIN_CARTAS", [], [f"{label}: no tienes {', '.join(set(core) - set(owned_core))}."])
            for c in owned_core:
                m.Add(x[c, d] == 1)
            if arch.get("core_any"):
                opts = _resolve(arch["core_any"], player)
                if not opts:
                    return SolveResult(False, "SIN_CARTAS", [], [f"{label}: no tienes ninguna de {arch['core_any']}."])
                m.Add(X(opts) >= 1)
            for g in arch.get("groups", []):
                opts = _resolve(g["from"], player)
                need = min(g["min"], len(opts))
                if need < g["min"]:
                    notes.append(f"{label}: solo tienes {len(opts)} de {g['from']} (se pedían {g['min']}).")
                if need:
                    m.Add(X(opts) >= need)
            for c in _resolve(arch.get("forbid", []), player):
                m.Add(x[c, d] == 0)

        elix10 = sum(round(player.cards[c].elixir * 10) * x[c, d] for c in ids)
        m.Add(elix10 >= round(lo * 10 * rules["size"]))
        m.Add(elix10 <= round(hi * 10 * rules["size"]))

        evo_d = [(c, v) for (c, dd), v in e.items() if dd == d]
        for c, v in evo_d:
            m.Add(v <= x[c, d])
        m.Add(sum(v for _, v in evo_d) <= rules["evo_slots"])

        terms = [round(evals[c].value * SCALE) * x[c, d] for c in ids]
        terms += [round(evals[c].evo_bonus * SCALE) * v for c, v in evo_d]

        for (a, b), (w, _) in syn.items():
            y = m.NewBoolVar(f"y[{a}][{b}][{d}]")
            if w > 0:
                m.Add(y <= x[a, d])
                m.Add(y <= x[b, d])
            else:
                m.Add(y >= x[a, d] + x[b, d] - 1)
            terms.append(round(w * SCALE) * y)

        for rb in game.rules["role_bonuses"]:
            group = [c for c in ids if has_role(c, rb["any_roles"])]
            if group:
                z = m.NewBoolVar(f"rb[{rb['name']}][{d}]")
                m.Add(z <= X(group))
                terms.append(round(rb["bonus"] * SCALE) * z)

        for prev in req.exclude_decks:
            prev_ids = _resolve(prev, player)
            m.Add(X(prev_ids) <= len(prev_ids) - 1)

        deck_scores.append(sum(terms))

    if req.n_decks > 1 and len(set(archs)) == 1:
        # Los mazos son intercambiables: ordenarlos por puntaje elimina soluciones repetidas.
        for d in range(req.n_decks - 1):
            m.Add(deck_scores[d] >= deck_scores[d + 1])
    if req.n_decks > 1:
        worst = m.NewIntVar(-10**9, 10**9, "worst")
        for s in deck_scores:
            m.Add(worst <= s)
        m.Maximize(req.balance_weight * worst + sum(deck_scores))
    else:
        m.Maximize(deck_scores[0])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = req.time_limit
    solver.parameters.num_workers = 8
    status = solver.Solve(m)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        notes.append("No existe un mazo que cumpla todas las reglas con tus cartas. "
                     "Prueba a relajar el rango de elixir, quitar cartas bloqueadas o cambiar de arquetipo.")
        return SolveResult(False, status_name, [], notes)
    if status == cp_model.FEASIBLE:
        best, bound = solver.ObjectiveValue(), solver.BestObjectiveBound()
        gap = abs(bound - best) / max(1.0, abs(best)) * 100
        notes.append(f"Se alcanzó el límite de tiempo: la solución está como máximo a un {gap:.1f}% del óptimo teórico.")

    decks = []
    for d in D:
        cards = [c for c in ids if solver.Value(x[c, d])]
        evos = [c for (c, dd), v in e.items() if dd == d and solver.Value(v)]
        # Orden para el enlace del juego: evoluciones primero (ocupan los primeros espacios).
        cards.sort(key=lambda c: (c not in evos, -evals[c].value))
        ev = evaluate_deck(cards, evos, player, game, evals)
        ev["archetype"] = game.archetypes[archs[d]]["name"] if archs[d] else None
        decks.append(ev)
    return SolveResult(True, status_name, decks, notes)

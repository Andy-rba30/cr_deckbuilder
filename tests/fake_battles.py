"""Batallas sintéticas con efectos conocidos, en el formato que devuelve la API (battlelog)."""
import math
import random
from datetime import datetime, timedelta, timezone

DECKS = {
    "hog": ["Hog Rider", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "Fireball", "The Log"],
    "golem": ["Golem", "Night Witch", "Baby Dragon", "Lumberjack", "Tornado", "Lightning", "Barbarian Barrel",
              "Mega Minion"],
    "bait": ["Goblin Barrel", "Princess", "Goblin Gang", "Knight", "Inferno Tower", "Rocket", "The Log", "Ice Spirit"],
    "lava": ["Lava Hound", "Balloon", "Mega Minion", "Skeleton Dragons", "Tombstone", "Fireball", "Zap", "Guards"],
    "xbow": ["X-Bow", "Tesla", "Archers", "Knight", "Skeletons", "Ice Spirit", "Fireball", "The Log"],
    "miner": ["Miner", "Wall Breakers", "Poison", "Bomb Tower", "Electro Spirit", "Knight", "Bats", "Brand New Card"],
}
POOL = sorted({c for d in DECKS.values() for c in d} | {"Valkyrie", "Bandit", "Firecracker", "Arrows"})
STRENGTH = {"Hog Rider": 0.6, "Golem": -0.6}   # efecto oculto en log-odds
LEVEL_EFFECT = 0.5                                # log-odds por nivel de ventaja
TAG_CHARS = "0289PYLQGRJCUV"


def tag(i: int) -> str:
    s = ""
    while True:
        s = TAG_CHARS[i % 14] + s
        i //= 14
        if not i:
            break
    return "#" + s.rjust(4, "P")


def _deck(rng):
    d = list(DECKS[rng.choice(list(DECKS))])
    if rng.random() < 0.4:   # variantes: cambia una carta al azar
        d[rng.randrange(8)] = rng.choice([c for c in POOL if c not in d])
    return d


def make_battles(n=1500, seed=1, now=None, battle_type="PvP"):
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    out = []
    for i in range(n):
        decks = [_deck(rng), _deck(rng)]
        levels = [rng.choice([13, 14, 15]), rng.choice([13, 14, 15])]
        z = (sum(STRENGTH.get(c, 0.0) for c in decks[0]) - sum(STRENGTH.get(c, 0.0) for c in decks[1])
             + LEVEL_EFFECT * (levels[0] - levels[1]))
        first_wins = rng.random() < 1 / (1 + math.exp(-z))
        players = []
        for side in range(2):
            won = first_wins == (side == 0)
            players.append({
                "tag": tag(2 * i + side), "crowns": 1 if won else 0,
                # Todas como comunes (maxLevel 16) para que el nivel ya esté normalizado.
                "cards": [{"name": c, "level": levels[side], "maxLevel": 16} for c in decks[side]],
            })
        out.append({"type": battle_type, "battleTime": (now - timedelta(minutes=i)).strftime("%Y%m%dT%H%M%S.000Z"),
                    "team": [players[0]], "opponent": [players[1]]})
    return out


RANDOM_POOL = ["Hog Rider", "Earthquake", "Musketeer", "Cannon", "Ice Golem", "Skeletons", "Ice Spirit", "Fireball",
               "The Log", "Knight", "Archers", "Valkyrie", "Baby Dragon", "Zap", "Arrows", "Minions", "Bats",
               "Tesla", "Goblin Gang", "Mega Minion"]
PAIR_EFFECT = {("Earthquake", "Hog Rider"): 0.8}   # juntas ganan más de lo que suma cada una


def make_random_battles(n=3000, seed=2, now=None, pair_effect=PAIR_EFFECT):
    """Mazos al azar de un grupo pequeño de cartas: todas las parejas aparecen juntas y por separado,
    así se puede medir el efecto de un par. Sin efectos de cartas solas ni de nivel."""
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    out = []
    for i in range(n):
        decks = [rng.sample(RANDOM_POOL, 8), rng.sample(RANDOM_POOL, 8)]
        z = sum(eff * ((a in decks[0] and b in decks[0]) - (a in decks[1] and b in decks[1]))
                for (a, b), eff in pair_effect.items())
        first_wins = rng.random() < 1 / (1 + math.exp(-z))
        players = [{"tag": tag(2 * i + s), "crowns": int(first_wins == (s == 0)),
                    "cards": [{"name": c, "level": 14, "maxLevel": 16} for c in decks[s]]} for s in range(2)]
        out.append({"type": "PvP", "battleTime": (now - timedelta(minutes=i)).strftime("%Y%m%dT%H%M%S.000Z"),
                    "team": [players[0]], "opponent": [players[1]]})
    return out

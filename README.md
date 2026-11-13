# Recomendador de mazos de Clash Royale (prototipo personal)

Lee tu cuenta con la API oficial de Supercell y arma mazos con un modelo de
**programación lineal entera (ILP)** resuelto con **OR-Tools CP-SAT**.

| Modo | Qué hace |
|---|---|
| ⭐ Óptimo | El mejor mazo posible con tus cartas y niveles, más alternativas que cambian al menos 3 cartas |
| 🧩 Arquetipo | Ranking de qué arquetipo te conviene + variantes de Log Bait, Bridge Spam, Beatdown, Miner Control, Hog Cycle, Asedio, LavaLoon, Graveyard, Royal Giant |
| ⚔️ Guerra de clanes | 4 mazos **sin cartas repetidas**, optimizados a la vez para que ninguno quede débil |
| 🛠️ Creador | Arma tu mazo a mano (＋ Añadir / ✕ Quitar), míralo evaluado al momento y **✨ Completar** rellena los huecos |
| 📈 Mejoras | Simula subir cada carta +1 nivel y te dice cuál mejora más tu mazo |
| 📊 Meta | Descarga batallas reales de jugadores de tu nivel y calcula fuerza de cartas y combos |
| 📚 Colección | Galería de tus cartas con nivel coloreado, filtros y valor |

Los mazos se muestran como en el juego: cuadrícula de 4×2 con imagen de cada carta (si la API la
trae), costo de elixir, nivel coloreado (verde = a tu nivel de referencia, ámbar = 1 abajo,
rojo = 2 o más), marca **EVO** y 👑, elixir medio, costo de ciclo, botón para copiar al juego y
barras de ataque, defensa, sinergia y versatilidad. El tema oscuro está en `.streamlit/config.toml`.

## Instalación

Necesitas Python 3.10 o superior.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     |  Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Probar sin clave (modo demo)

```bash
streamlit run app.py
```
Se abre en el navegador; elige **Demo** en la barra lateral. También por consola:

```bash
python cli.py --demo --mode optimal --alternatives 2
python cli.py --demo --mode archetype --archetype log_bait
python cli.py --demo --mode ranking
python cli.py --tag "#ABC123" --mode meta --players 150   # descarga batallas reales (necesita clave)
python cli.py --demo --mode war
python cli.py --demo --mode upgrades
```

## Usar tu cuenta real

1. Entra a https://developer.clashroyale.com, crea una cuenta y una **API key**.
   Al crearla te pide la **IP pública** desde la que la usarás (búscala con "cuál es mi IP").
2. Copia `.env.example` como `.env` y pega tu clave en `CR_API_KEY`.
3. En la app elige **Player Tag (API)** y escribe tu tag (por ejemplo `#ABC123`).

> Si tu IP de casa cambia, la API responderá **403** y tendrás que crear una clave nueva
> con la IP nueva. Otra opción es el proxy de RoyaleAPI (ver `.env.example`).

Las respuestas se guardan 10 minutos en `.cache/` para no gastar peticiones.
También puedes guardar la respuesta JSON de `/players/{tag}` y cargarla con **Archivo JSON**.

## Cómo decide el motor

**Valor de cada carta** (`crdeck/scoring.py`)
```
valor = meta × factor_nivel − castigo_por_puntos_de_quiebre (+ bonus campeón)
factor_nivel = 1 − sens × (1 − e^(−0.45 × diferencia))    si la carta está bajo el nivel de referencia
```
- `sens` cerca de 0 (Esqueletos, Espíritus) → casi no pierde valor si está baja.
- `sens` cerca de 1 (Mosquetera, Tres mosqueteras) → pierde mucho valor.
- **Nivel de referencia** = nivel típico de tus rivales (por defecto, la mediana de tus mejores 24 cartas).
- **Importancia del nivel**: 0 ignora niveles, 2 los castiga el doble.

**Modelo ILP** (`crdeck/solver.py`) — variables sí/no por carta y mazo:
- Restricciones duras: 8 cartas, 1–2 condiciones de victoria, ≥2 antiaéreas, 1–3 hechizos,
  máx. 1 tanque, máx. 2 estructuras, máx. 1 campeón, rango de elixir, espacios de evolución.
- Puntaje: valor de las cartas + bonus de evoluciones + sinergias entre pares + roles cubiertos.
- Guerra: además, cada carta en un solo mazo, y se maximiza **el mazo más débil** (×10) + el total.
- Arquetipos: solo admiten las condiciones de victoria de su plantilla (`core`, `core_any`, `groups`
  o `extra_wincons`), para que no se cuele, por ejemplo, un Montapuercos en un Graveyard.
- Alternativas: se vuelve a resolver exigiendo que cambien al menos N cartas (3 por defecto;
  ajustable en la barra lateral o con `--min-diff`) respecto a cada mazo ya mostrado.

Si el tiempo se acaba, la app te dice a qué distancia (en %) está la solución del óptimo teórico.
En Guerra, el modelo arranca desde 4 mazos armados uno por uno, así llega antes a buenas soluciones.

## Meta con batallas reales (`crdeck/battles.py`, `crdeck/meta.py`)

En la pestaña **📊 Meta** (con tu Player Tag) o con `--mode meta`, la app descarga tu historial
de batallas, luego el de tus rivales, el de los rivales de ellos, etc. Como el juego empareja
jugadores parecidos, la muestra refleja **el meta de tu nivel**. Solo cuentan batallas 1 contra 1
(los tipos están en `rules.yaml`), cada una se guarda una vez en `data/battles.json` (no se sube a git)
y las de más de 28 días se descartan, porque el balance cambia cada mes.

- **Fuerza de cada carta**: regresión logística sobre quién ganó cada batalla, con las cartas de los
  dos mazos y la diferencia de nivel. Así una carta no parece fuerte solo porque la juega gente con
  más nivel o porque siempre va con otra carta fuerte. También da cuánto vale 1 nivel de ventaja.
- **Meta final** = mezcla de los datos con `cards.yaml` según cuántas partidas hay: con 100 partidas
  pesan igual; con pocas manda el catálogo. Los datos deciden el orden de las cartas y la escala sale
  de `cards.yaml`, para no desbalancear el modelo. Las cartas nuevas que faltan en el catálogo
  también reciben su meta de los datos.
- **Sinergias**: cuántas veces más se juegan dos cartas juntas de lo esperado si fuera al azar, más
  (con mucha prudencia) cuánto más ganan juntas. Se suman a las de `synergies.yaml`. La mitad del
  cupo es para combos y la otra mitad para cartas que casi nunca van juntas.
- Se activa o desactiva con el interruptor **Usar meta de batallas reales** (o `--no-battle-meta`).
  Todos los parámetros están en `rules.yaml`, sección `battle_meta`, y se pueden cambiar sin volver
  a descargar.

Con 100 jugadores son unas 100 peticiones a la API (cerca de 1 minuto) y unas 1.500–2.500 batallas.

## Archivos que puedes editar (sin tocar código)

| Archivo | Contenido |
|---|---|
| `data/cards.yaml` | Roles, sensibilidad al nivel, fuerza en el meta y bonus de evolución de cada carta |
| `data/synergies.yaml` | Combos (+) y antisinergias (−) con su peso y explicación |
| `data/interactions.yaml` | Puntos de quiebre (ej. Bola de fuego vs Mosquetera) |
| `data/rules.yaml` | Reglas del mazo: límites por rol, elixir, espacios de evolución, bonus suaves y parámetros del meta de batallas |
| `data/archetypes.yaml` | Plantillas de arquetipos: núcleo, grupos, cartas prohibidas, elixir |

Roles disponibles: `win_condition, tank, mini_tank, building, air_defense, small_spell, big_spell,
splash, anti_tank_dps, dps, ranged_dps, support, cycle, cheap_defense, swarm, bait, reset`.

## ⚠ Limitaciones importantes

- Los valores `meta`, `sens` y `evo` de `cards.yaml` son **estimaciones iniciales**. El resultado
  es tan bueno como esos datos: ajústalos según el meta de la temporada.
- Los puntos de quiebre de `interactions.yaml` son **ejemplos sin verificar**.
- Los nombres en `cards.yaml` deben coincidir con los que devuelve la API (en inglés).
  Las cartas nuevas que falten salen listadas en la app; agrégalas al YAML.
- Supercell cambia los espacios especiales del mazo (evoluciones, comodín, héroes) según la temporada:
  ajusta `evo_slots` en `rules.yaml`. Los héroes no están modelados todavía.
- El modo Guerra puede tardar unos 20 s (más en computadoras con pocos núcleos).
- El jugador demo es inventado y sus IDs de cartas son de ejemplo.
- Uso personal. Si algún día lo publicas, revisa la Política de contenido de fans de Supercell.

## Pruebas

```bash
python -m pytest -q tests
```

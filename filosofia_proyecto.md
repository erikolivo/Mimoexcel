# Filosofía y lógica del proyecto: Alertas de gol en vivo

> Nota (agosto 2026): este documento se mantiene sin cambios tras la
> migración de API-Football a ESPN. Los principios de fondo (nunca
> fallar en silencio, minimizar peticiones, documentar cada decisión
> con el porqué) siguen aplicando igual — ver `MIGRACION_ESPN.md` para
> el detalle de qué cambió puntualmente en su implementación.

## 1. Por qué existe este proyecto

Nació con un objetivo distinto al actual: detectar oportunidades de apuesta
en vivo sobre equipos favoritos (cuota inicial ≤1.35), usando cuotas reales
de casas de apuestas y su evolución durante el partido.

Ese diseño original se abandonó por una razón concreta, no por capricho:
**no existe una fuente de cuotas de fútbol en vivo, gratuita, y de acceso
legal desde tu ubicación.** Se investigaron tres caminos y los tres
resultaron cerrados:

- **The Odds API y proveedores similares**: su nivel gratuito no cubre
  fútbol (solo NBA/MLB) o tiene límites de cupo demasiado bajos para uso
  diario continuo.
- **Betfair Exchange**: sí tiene API gratuita técnicamente viable, pero
  Betfair no está disponible legalmente desde tu país.
- **Casas de apuestas legales locales** (Rushbet, Betsson, Codere, etc.):
  ninguna ofrece una API pública — son productos de consumo, no
  proveedores de datos.

Ante esto, el proyecto se adaptó: en vez de cuotas reales, usa **Elo +
Goal Index** como sustituto de "cuánto favorito es un equipo", y
**estadísticas en vivo** (tiros, córners, posesión) como sustituto de "el
mercado está reaccionando". Esta sustitución quedó documentada
explícitamente desde el principio para que nunca se confunda con datos
reales de mercado.

> Actualización (agosto 2026): ESPN sí trae cuotas reales de DraftKings
> embebidas de forma gratuita para las ligas principales — ver
> `MIGRACION_ESPN.md`. Para el resto de ligas, el proxy Elo+Goal Index
> sigue siendo la única fuente disponible, y sigue documentado como tal.

## 2. Qué se quiere del proyecto — y cómo cambió

**Versión original:** pocas apuestas de "mucho valor" (cuota ≤1.35),
alertadas solo cuando el marcador y el contexto sugerían que la cuota real
habría subido mucho.

**Versión actual (la vigente):** el objetivo cambió deliberadamente a
**seguimiento del mayor número de partidos posible**, con alertas que
avisan **cuándo es probable que se anote un gol pronto** — no solo "va a
ganar el favorito", sino un seguimiento más rico: quién está generando
peligro, en qué momento del partido, y con qué intensidad.

La filosofía de fondo en esta versión es: **más cobertura y más matices
de alerta, a cambio de aceptar que el modelo es una aproximación que se
irá afinando con datos reales** — no un sistema que se declara "correcto"
desde el día uno.

## 3. Cuándo debe usarse — el ciclo diario

El sistema no está pensado para que lo revises constantemente; está
diseñado para que **Telegram te avise solo cuando hay algo que valga la
pena ver**:

| Momento | Qué recibes | Por qué a esa hora |
|---|---|---|
| 04:00 en adelante | (nada visible) | Fase 1 arma la lista del día, reintentando hasta lograrlo — antes de que arranque cualquier partido |
| 06:00 | Reporte de resultados de AYER (✅/❌ por partido, % de aciertos, cupo de API usado) | Para que empieces el día sabiendo cómo le fue al sistema, sin tener que revisar nada tú mismo |
| 07:00 | Resumen de los partidos de HOY | Una vez que ya hubo tiempo de armar la lista completa |
| Durante los partidos | Alertas de gol en vivo (7-10 tipos distintos) | Solo mientras el partido está en su ventana horaria real |
| 23:30 | (nada visible) | Fase 4 cierra resultados, archiva el día, actualiza el Excel |

## 4. Cómo se gestionan las peticiones a las APIs

Este es uno de los ejes centrales del diseño. La filosofía aplicada, en
orden de importancia:

1. **Nunca gastar una petición si se puede evitar.**
2. **1 petición sirve para todos los partidos posible, cuando aplica.**
3. **Frecuencia adaptativa según la carga real.**
4. **Nunca duplicar cuentas para esquivar un límite** — prohibido
   explícitamente por API-Football, y aplicado igual como principio
   general aunque el proveedor actual (ESPN) no requiera cuenta.
5. **Reintentos con paciencia, no con fuerza bruta.**
6. **El propio sistema se audita a sí mismo** — cuenta cuántas
   peticiones usó y te lo reporta cada día.

## 5. Filosofía de los mensajes de Telegram

- **Resumen de las 7am** — panorama del día.
- **Alertas en vivo** — cada una nombra una situación específica y
  reconocible, no un genérico "algo está pasando".
- **Sin límite de alertas por partido** — narración progresiva.
- **Cada alerta trae sus propias estadísticas** para que decidas con tu
  propio criterio.
- **Reporte de las 6am** — el mensaje más importante para la salud del
  proyecto a largo plazo.

## 6. Principios de diseño aplicados consistentemente

- **Nunca fallar en silencio.**
- **Preferir la solución gratuita que ya se tiene** antes que sumar una
  fuente de pago o una técnica riesgosa.
- **Todo cambio de lógica queda documentado con el porqué.**
- **Los números de arranque se tratan como puntos de partida
  razonables, no como verdades calibradas.**
- **Un resultado sorprendente se investiga con datos reales antes de
  tocar el código** — nunca se ajusta el modelo reaccionando a una sola
  muestra.

## 7. Addendum v2 — rediseño del rating y el motor de alertas

Ver el README para el detalle completo del rediseño Glicko-2 + momentum
separado de la expectativa pre-partido.

## 8. Addendum v3 — migración de API-Football a ESPN

Ver `MIGRACION_ESPN.md` para el detalle completo: por qué se migró, qué
se verificó antes de escribir código, qué se ganó, qué se perdió, y qué
riesgos se aceptaron explícitamente.

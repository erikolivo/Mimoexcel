# Consolidación elo-gol-live

> Nota (agosto 2026): este documento describe la consolidación original
> de los 6 repos de fútbol (previa a la migración de API-Football a
> ESPN). Se mantiene tal cual por su valor histórico — explica por qué
> el proyecto está estructurado como está. Para la migración de
> proveedor de datos en vivo, ver `MIGRACION_ESPN.md`.

Este repo nace de comparar el código real (no solo los README) de los 6
repos de fútbol de erikolivo: `alertas-apuestas`, `Predicciones-Elo`,
`ole-ole`, `elo-nuevo`, `flow-elo`, `GEM1`. Ninguno estaba en producción,
así que se pudo elegir libremente sin preocuparse por migración.

## Qué se descartó y por qué

- **alertas-apuestas / Predicciones-Elo / ole-ole**: son etapas
  anteriores del mismo diseño. `lpi_engine.py` y `odds_validation.py` de
  ole-ole son los borradores tempranos de lo que hoy son `momentum.py` y
  `cuotas_reales.py`. No tienen código único que no exista ya, mejorado,
  en elo-nuevo/flow-elo/GEM1.
- **elo-nuevo**: mismo diseño que flow-elo/GEM1 pero con solo 8 commits
  (vs 134 de flow-elo) — versión menos iterada, sin las mejoras de cuotas
  reales.

## Base elegida: flow-elo (134 commits)

Se usó como esqueleto porque es la versión más iterada y mejor
documentada de la línea moderna (rating propio Glicko-2 + momentum en
vivo separado de la expectativa pre-partido + resolución de país por
equipo + cuotas reales).

## Qué se trajo de GEM1

- **`storage.py`**: capa única de lectura/escritura de JSON. Se incluye
  como utilidad disponible, pero **no se forzó su uso en el resto de
  los módulos**.
- **`poisson_model.py`**: la versión de GEM1 pondera el rating por el RD
  (incertidumbre) de Glicko-2 antes de convertirlo en goles esperados
  (`aplicar_rd()`), y usa promedios de goles dinámicos por equipo en vez
  de un promedio de liga fijo.

## Bug encontrado y corregido durante la consolidación

El "promedio de goles dinámico" de GEM1 dependía de que el diccionario
de `goal_index` trajera `goles_favor_prom` / `goles_contra_prom` por
equipo. `fetch_data.calcular_goal_index()` sí los calculaba, pero
`goal_index.py::_mezclar()` los descartaba al combinar forma reciente +
temporada — esos dos campos nunca llegaban a `poisson_model.py`. Se
corrigió `_mezclar()` para propagar ambos campos con el mismo blend
60/40 que ya se usaba para `goal_index`.

## Decisión deliberada: NO se forzó el refactor a storage.py en todo el repo

Se prefirió dejar los módulos grandes (`cerrar_resultados.py`,
`monitor.py`, `reporte_diario.py`, `resumen.py`, `cuota_odds_api.py`)
con la versión de flow-elo (probada en 134 commits) en vez de arriesgar
una regresión no detectada solo por prolijidad arquitectónica.

## Por qué NO se tomó team_resolver.py ni seleccionar_partidos.py completos de GEM1

La versión de GEM1 de `team_resolver.py` no cacheaba el país en disco
y no tenía la verificación cruzada por confederación completa que sí
tiene flow-elo. Por eso se mantuvo el `team_resolver.py` de flow-elo
tal cual.

## Resumen de origen por archivo (histórico, previo a la migración ESPN)

| Archivo | Origen | Cambios |
|---|---|---|
| `poisson_model.py` | GEM1 | ninguno |
| `storage.py` | GEM1 | ninguno (disponible, sin forzar su uso) |
| `goal_index.py` | flow-elo | fix: propaga goles_favor_prom/goles_contra_prom |
| `seleccionar_partidos.py` | flow-elo | adaptado a la firma nueva de poisson_model |
| Todo lo demás | flow-elo | sin cambios |

Ver `MIGRACION_ESPN.md` para los cambios posteriores por la migración de
proveedor de datos en vivo.

## Refactorización de alertas (septiembre 2026, rama mejoras-alertas)

Se implementó una refactorización de 4 fases para mejorar la precisión
y cobertura del sistema de alertas:

### Fase A — Resolución y mensajes
- Criterios individuales por tipo de alerta (`CRITERIO_POR_TIPO` en
  `resolucion_alertas.py`) reemplazan la lógica monolítica anterior.
- Mensajes en vivo incluyen resultado si ya terminó el partido.
- Auditoría en cierre (`cerrar_resultados.py`) usa las mismas reglas
  que el monitoreo en vivo (X1).
- 21 tests en `tests/test_resolucion.py` + `tests/test_registro_mensajes.py`
  + `tests/test_auditoria_excel.py`.

### Fase B — Reglas de alerta
- 12 cambios (C1-C12) en `_evaluar_alertas`:
  - C1: `posible_victoria_favorito` exige presión fav ≥ 10 y z ≥ 1.8
  - C2: `posible_empate` → `posible_descuento`, solo favorito directo, min ≤ 40
  - C3: `ampliacion_marcador` exige presión fav ≥ 14
  - C4: `cuidado_rival_presiona` exige sot_riv ≥ 2 y presión rival ≥ 16
  - C5: `alerta_1er_tiempo` solo favorito directo, min ≤ 30, z ≥ 1.8
  - C6: `gol_de_cierre` con dif ∈ {-1,0}, min ≤ 80, z ≥ 3.8
  - C7: `fav_domina_no_gana` con tope de 2 goles de déficit
  - C8: `no_fav_domina` con presión rival ≥ 11 y dif = 0
  - C9: `value_alert` desactivado (bug B7 corregido, sin lift real)
  - C11: `cambio_momentum` desactivado (lift débil)
  - C12: `tarjeta_roja` sin límite de una por partido
- Resultado: 77.1 → 32.0 alertas/día (−58%), con lift mejorado en
  todos los tipos que se mantienen activos.
- 24 tests en `tests/test_reglas_disparo.py` + 5 en `tests/test_idv.py`.

### Ajustes 2026-09 (Round 5 — decisiones del usuario)
- C1: `posible_victoria_favorito` → pf ≥ 10, z ≥ 1.8 (57%→60%)
- C4: `cuidado_rival_presiona` → pr ≥ 16 (21%→43%, n 89→14)
- C8: `no_fav_domina` → solo dif = 0 (48%→52%)
- `siguen_empatados_22` → z ≥ 1.1 (69%→82%)
- `siguen_empatados_55/70` → solo registro, sin envío Telegram
- `tarjeta_roja` → solo registro; criterio: siguiente gol del equipo SIN la roja
- `penal` → desactivada por completo (`ALERTA_ACTIVA["penal"]=False`)
- `value_alert` / `cambio_momentum` → se mantienen apagadas (sin lift real)
- Mecanismo `TIPOS_SIN_TELEGRAM` en `monitor.py`: evalúa y registra sin enviar
- `ENVIAR_RESULTADO_PARTIDO = False` → aviso "Partido finalizado" desactivado (solo resoluciones de alertas; reactivar poniendo True)

### Fase C — Cobertura aviso final
- F1: `liga_slug == "all"` ya no se salta — usa `all/scoreboard`
  como fallback para detectar fin de partido y enviar aviso final.
- F2: Ventana horaria extendida de 130 a 240 minutos.
- F3: Cron 08:00 UTC agregado para cubrir hueco entre jobs.
- F4: Alertas pendientes se resuelven en `cerrar_resultados.py`
  usando `resolver_pendientes()`.

### Verificación
- `backtest_mejoras.py`: reproduce Anexo A exacto (77.1→32.0).
- 50/50 tests pasan (`pytest`).
- Commits: `1c0ed41` (A), `adf5278` (B), `d0868f7` (C).


## Rama fix/nivel-y-ratings (2026-10-01 - Nivel Actual, Estilo y ratings)

### Fase 0 - verificacion del calendario de ESPN (fixture guardado)
- Fixture `tests/fixtures/espn_schedule_sample.json`: schedule de equipo
  solo trae partidos terminados (score dict); futuros/en curso viven solo
  en scoreboard de liga (score string). Status en schedule =
  `competitions[0].status.type`; `competitor["id"] == team["id"]`;
  temporada actual = `season={anio}`. Detalle completo en
  `MIGRACION_ESPN.md`.
- Bugs latentes hallados y corregidos: URL de ligas internacionales
  (`all/schedule?team=` daba 404 -> historial vacio cacheado 7 dias),
  `.get("value", 0)` inventaba 0-0, score string hacia estallir
  `int()`, y `_es_amistoso` nunca funciono (marcador real en
  `event.league`, no en `competitions[].type`).

### Nivel Actual (Tareas 1-4)
- Historial: solo terminados, sin amistosos, dos temporadas, cache 12 h
  con clave `v2|{team_id}|{slug}` (claves viejas huerfanas, sin borrar).
- Formula: `(0.40*forma + 0.40*sede + 0.20*goles)/10`, ventana 6 con
  decaimiento 0.85, sede = ultimos 6 de esa sede (fallback global si
  hay <2), minimo 4 partidos, colores sin cambios (8/6/4).
- Cada alerta guarda `nivel_local`/`nivel_visitante` (mensaje visible y
  Excel sin cambios).

### Estilo de juego (Tarea 3)
- `_obtener_datos_estilo` filtra por `HomeTeam`/`AwayTeam` reales (antes
  usaba columnas inexistentes `local`/`visitante` -> siempre vacio, el
  estilo nunca se mostraba). Umbrales de `_calcular_estilo_juego` SIN
  cambios (sin calibracion).
- Seguimiento (2026-09-30, "el estilo no llega a Telegram"):
  1. La Tarea 3 estaba sin mergear: en `main` seguia el bug de las
     columnas -> 0% de estilo. Se deploya con este PR.
  2. Temporada `2526` hardcodeada (caducada): ahora `temporada_actual()`
     autodetecta (arranque en agosto -> "2627"); el cache de estilo pide
     anterior+actual para no quedarse sin datos al arrancar la temporada.
     `goal_index.py` tambien usa ambas temporadas.
  3. Cobertura ampliada de 16 a 21 ligas con stats completas verificadas
     en vivo (2526 y 2627): + eng.3/eng.4 (E2/E3), por.2 (P2),
     sco.2/sco.3 (SC1/SC2). NO entran ARG/BRA/MEX/USA (football-data
     `new/*.csv` solo trae marcador+cuotas, sin stats de tiro) ni
     ger.3/ned.2/bel.2/tur.2 (el servidor responde 300 = sin archivo).
     `obtener_resultados_liga` ahora trata el 300 como vacio (antes el
     HTML de "sugerencias" pasaba como si fuera CSV).
  4. Alias de nombres ESPN -> football-data (37 pares, ej. "Sporting CP"
     -> "Sp Lisbon", "Wolverhampton Wanderers" -> "Wolves"): descubiertos
     comparando nombres reales del scoreboard de ESPN (4 fechas de la
     temporada 2026-27) contra los CSV de las 21 ligas; 35 fallos
     detectados, todos resueltos (test `test_alias_resuelve_nombres`).

### Ratings Fase 2 (Tareas 5-9)
- RD combinado: `RD_EFECTIVO_CLUBELO = 50` (aplicar_rd no borra la
  senal de ClubElo al 0% de peso propio).
- Semilla: equipos nuevos/registros vacios arrancan en el Elo de
  ClubElo con `RD_SEMILLA_CLUBELO = 150` (resiembra una sola vez).
- Calibracion por liga: media de (elo - rating propio) con >=8 partidos
  sobre >=6 equipos, sumada a toda la liga; idempotente; solo manual
  (`bootstrap_ligas.py --calibrar` o al final de un bootstrap) - NO en
  workflows diarios.
- Peso: bootstrap cuenta 0.5 (`n_efectivo`), `n` reportado sigue total.
- Ventaja local: `VENTAJA_LOCAL_ELO` (70, importada de poisson_model)
  aplicada en cerrar_resultados y bootstrap, respetando `neutral`, solo
  hacia adelante.
- Poisson: matriz de marcadores renormalizada (suma exactamente 1).
- Glicko-2 verificado contra el paper de Glickman (1464.06 / 151.52 /
  0.05999).

### Decisiones de NO cambiar (confirmadas en el PR)
- Ajuste por calidad del rival en el Nivel Actual: no (los campos
  quedan guardados en cada alerta para decidir con evidencia).
- Goal Index doble en poisson_model, Dixon-Coles, umbrales de estilo: no.
- `PESO_MAXIMO = 1.0` y tabla hasta 100%: intactos; tension con el
  docstring "nunca se reemplaza por completo" anotada para decidir
  despues.

### Verificacion
- `pytest` en verde (140 tests), `py_compile` limpio; tests con
  tmp_path (ninguno escribe en `data/`). Sin cambios en workflows,
  requirements ni umbrales de alertas.

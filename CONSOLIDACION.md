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
  - C1: `posible_victoria_favorito` exige presión fav ≥ 8
  - C2: `posible_empate` → `posible_descuento`, solo favorito directo, min ≤ 60
  - C3: `ampliacion_marcador` exige presión fav ≥ 11
  - C4: `cuidado_rival_presiona` exige sot_riv ≥ 2
  - C5: `alerta_1er_tiempo` solo favorito directo, min ≤ 30
  - C6: `gol_de_cierre` con dif ∈ {-1,0}, min ≤ 84, z ≥ 3.2
  - C7: `fav_domina_no_gana` con tope de 2 goles de déficit
  - C8: `no_fav_domina` con presión rival ≥ 11 y dif ≥ 0
  - C9: `value_alert` desactivado
  - C11: `cambio_momentum` desactivado
  - C12: `tarjeta_roja` sin límite de una por partido
- Resultado: 77.1 → 32.0 alertas/día (−58%), con lift mejorado en
  todos los tipos que se mantienen activos.
- 24 tests en `tests/test_reglas_disparo.py` + 5 en `tests/test_idv.py`.

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

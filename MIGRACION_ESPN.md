# Migracion de API-Football a ESPN (agosto 2026)

## Por que se migro

La cuenta de API-Football quedo suspendida. Se investigaron 3 cuentas
nuevas para reabrir acceso y las 3 fueron bloqueadas -- no es una
solucion viable ni permitida por los terminos de servicio de
API-Football (que prohiben explicitamente multiples cuentas para
esquivar limites). El seguimiento en vivo es una pieza central e
innegociable del proyecto, asi que se necesitaba un proveedor nuevo.

## Que se evaluo y por que se descarto

- **football-data.org**: gratis, pero solo cubre 12 competiciones
  principales y sus datos vienen con retraso -- no sirve para
  seguimiento en vivo minuto a minuto.
- **Sportmonks**: cobertura completa (fixtures, eventos, estadisticas,
  xG en vivo), pero de pago desde el primer plan util (~€29/mes para 5
  ligas). Se descarto por ahora en favor de una opcion gratuita.
- **ESPN (backend JSON no oficial de espn.com)**: gratis, sin cuenta ni
  API key (elimina de raiz el problema de cuentas bloqueadas), con
  cobertura amplia de ligas y boxscore en vivo. Elegido.

## Como se verifico antes de escribir codigo

No se escribio ni una linea de codigo de produccion sin evidencia real:

1. Se confirmo que el endpoint responde sin autenticacion
   (`site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard`).
2. Se busco y seguiste un partido REAL EN VIVO: Queretaro @ Seattle
   Sounders FC (Leagues Cup), 09-ago-2026, minuto 77'.
3. Se confirmo el formato EXACTO del boxscore en vivo de ese partido
   (lista de `{name, displayValue, label}` por equipo, con
   `shotsOnTarget`, `totalShots`, `wonCorners`, `redCards`,
   `penaltyKickShots`, `possessionPct`, etc.) antes de escribir
   `momentum.py`.
4. Se confirmo que ESPN trae cuotas reales de DraftKings embebidas en
   el mismo scoreboard que los fixtures -- hallazgo no buscado, mejora
   sobre el diseno anterior (The Odds API con cupo mensual limitado).

## Que se gano

- **Sin cuenta que bloquear** -- elimina el problema de raiz.
- **Cuotas reales gratis** (DraftKings via ESPN), sin gastar cupo de
  The Odds API. The Odds API se mantiene como respaldo secundario para
  ligas que ESPN/DraftKings no cubren.
- **Tarjeta roja y penal en el mismo boxscore** que ya se pedia para
  tiros/corners -- ya no hace falta la peticion aparte de eventos que
  costaba antes (1 peticion extra por revision).
- **Datos nuevos disponibles** (no explotados aun): tiros bloqueados,
  faltas, offside, lesiones por equipo (`teams/{id}/injuries`).

## Que se perdio (documentado para no buscarlo en vano)

- **Tiros dentro/fuera del area**: ESPN solo da tiros totales y tiros a
  puerta, no el desglose por ubicacion en la cancha que exponia
  API-Football. `momentum.py` se simplifico en consecuencia.
- **xG**: no confirmado que ESPN lo exponga para futbol. El sistema ya
  caia al proxy por tiros cuando no habia xG disponible, asi que no
  cambia el comportamiento, solo la frecuencia con la que se usa el
  proxy.
- **Cupo diario conocido**: ESPN no publica un limite oficial (a
  diferencia del 100/dia de API-Football). Ver `cuota_espn.py` para el
  detalle de por que esto cambia la forma del "ahorro" de peticiones,
  no lo elimina.
- **Pais del equipo por API**: ESPN no expone nacionalidad de club tan
  directo -- se uso el pais del estadio como aproximacion de ultimo
  recurso (tier 3, detras de liga domestica y Goal Index).

## Riesgos aceptados explicitamente

- **Sin SLA**: es un endpoint no oficial, puede cambiar o caerse sin
  aviso de ESPN.
- **Throttling no documentado**: reportes de la comunidad varian
  ampliamente (de "un par de cientos/dia" a "2500/dia"), ninguno
  verificado oficialmente. No hay numero confiable para presupuestar.
- **IP compartida de GitHub Actions**: un eventual bloqueo por abuso
  probablemente actua por IP, y los runners de GitHub Actions comparten
  rangos de IP entre miles de proyectos ajenos al tuyo. Riesgo real, sin
  forma de blindarse del todo.

## Piezas reconstruidas sin el original (leer antes de desplegar)

`fetch_data.py` y `monitor.py` originales nunca llegaron completos a la
conversacion donde se hizo esta migracion (se subieron los archivos
pero su contenido no paso al chat -- limitacion de la plataforma).
`fetch_data.py` de todos modos necesitaba reescritura completa por el
cambio de proveedor, asi que no hay perdida real ahi. `monitor.py`
(Fase 3, el motor de alertas) SI es una reconstruccion desde cero
basada en el README y en `momentum.py` -- los umbrales exactos de cada
tipo de alerta son valores de partida razonables, no los que ya estaban
calibrados con evidencia real en el Excel viejo. Compara con el
original si todavia lo tienes, sobre todo la logica de cuando NO
repetir una alerta ya enviada.

## Piezas nuevas de este archivo, listas para expandir

`LIGAS_ESPN` en `fetch_data.py` es una lista curada, no exhaustiva. Los
slugs marcados como "confirmado en vivo" en los comentarios se
verificaron durante esta migracion; el resto sigue el patron estandar
de ESPN (`pais.numero_de_division`) pero no se probo uno por uno. Si
una liga nueva falla, el log lo dice explicitamente -- se agrega/corrige
ese slug puntual sin tocar el resto, mismo espiritu que
`bootstrap_ligas.py` para agregar ligas de forma incremental.

"""
monitor.py
------------
FASE 3 -- RECONSTRUIDO durante la migracion a ESPN.

AVISO IMPORTANTE, leelo antes de desplegar: el monitor.py ORIGINAL
nunca llego a esta conversacion (se subio el archivo pero su contenido
no paso al chat -- limitacion de la plataforma, no un olvido). Todo lo
que sigue se reconstruyo a partir de:
  (a) la tabla de tipos de alerta descrita en README.md,
  (b) las funciones ya confirmadas de momentum.py,
  (c) el formato de datos de partidos_hoy.json que ya usan
      seleccionar_partidos.py, resumen.py y cerrar_resultados.py.

Los UMBRALES exactos (ej. "momentum >= 65% para alertar") son valores
de partida razonables, NO los que ya tenias calibrados con evidencia
real en el Excel. Si todavia tienes acceso al monitor.py original
(tu computadora, o el historial de git del repo viejo), compara la
logica exacta de cuando NO repetir una alerta ya enviada -- aqui se
simplifico a "no repetir el mismo tipo dentro de una ventana de N
minutos", que puede no ser exactamente lo que ya tenias afinado.

Qué SI cambio de forma segura (evidencia real de esta migracion):
  - Tarjeta roja y penal se detectan del MISMO boxscore de tiros/
    corners (momentum.hubo_tarjeta_roja / hubo_penal) -- ya no hace
    falta la peticion aparte de eventos que mencionaba el README viejo.
"""

import json
import datetime
from pathlib import Path

from fetch_data import obtener_boxscore_en_vivo
from telegram_utils import enviar_mensaje_telegram, escapar_html
from cerrar_resultados import calcular_acierto
import momentum

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_PARTIDOS = DATA_DIR / "partidos_hoy.json"

MINUTO_INICIO_CIERRE = 75
MAXIMO_MINUTO_ALERTAS_NO_CIERRE = 80

MINUTO_MINIMO_ALERTA_MOMENTUM = 15

# Emoji al inicio de cada mensaje segun el TIPO de pronostico (a pedido
# explicito, agosto 2026) -- distinto de la corona junto al nombre del
# equipo, que indica A QUIEN favorece. Van pegados juntos (tipo primero,
# corona despues) al lado del nombre del equipo favorito.
EMOJI_TIPO_PRONOSTICO = {
    "favorito_directo": "\U0001F3AF",   # 🎯
    "doble_oportunidad": "\U0001F500",  # 🔀
}
CORONA_FAVORITO = "\U0001F451"  # 👑

# =====================================================================
# NUEVO SISTEMA (agosto 2026, a pedido explicito) -- reemplaza el
# anterior de 2 capas (ventana sostenida + bono de ventana reciente)
# por decaimiento exponencial + z-score de confianza estadistica (ver
# momentum.py). En vez de ventanas fijas y un piso de volumen
# inventado a mano, cada evento pesa menos mientras mas viejo es, y el
# umbral de disparo es "que tan lejos esta del 50/50, en desviaciones
# estandar" -- eso ya incorpora el problema del volumen de forma
# matematica, sin necesitar un piso aparte.
# =====================================================================

UMBRAL_Z_ALERTA = momentum.UMBRAL_Z_CONFIANZA_MEDIA    # ~90% de confianza
UMBRAL_Z_CIERRE = 2.7                            # subido a pedido explicito, mas estricto
UMBRAL_Z_RIVAL = 2.7                             # rival domina: z-score minimo para alertar
UMBRAL_Z_1ER_TIEMPO = 1.28                              # ~80%, mas permisivo a proposito
MINUTO_INICIO_1ER_TIEMPO = 25
MINUTO_FIN_1ER_TIEMPO = 40

# =====================================================================
# IDV - INDICE DE DESVIACION DE VALOR (agosto 2026)
# Detecta cuando un equipo domina en partidos con cuotas parejas
# =====================================================================

UMBRAL_IDV_BAJO = 5
UMBRAL_IDV_MEDIO = 10
UMBRAL_IDV_ALTO = 20
MINUTOS_MINIMOS_IDV = 10


def _to_float(valor, default=0.0):
    """Convierte a float valores que la API de ESPN a veces entrega como
    string (ej. "55.3", "55%", None). Si no se puede convertir, usa default."""
    if valor is None:
        return default
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace("%", ""))
    except (ValueError, TypeError):
        return default


def _calcular_idv(partido, snap_actual, historial, minuto_int):
    cuota_local = partido.get("cuota_local_inicial")
    cuota_visitante = partido.get("cuota_visitante_inicial")
    if not cuota_local or not cuota_visitante or cuota_local <=0 or cuota_visitante <=0:
        return None

    favorito_es_local = partido["favorito_es_local"]
    gl, gv = snap_actual["goles_local"], snap_actual["goles_visitante"]

    diferencia_cuotas = abs(cuota_local - cuota_visitante)
    suma_cuotas = cuota_local + cuota_visitante
    if suma_cuotas ==0:
        return None
    od = 1 - (diferencia_cuotas / suma_cuotas)

    prob_esperada_local = (1/cuota_local) / (1/cuota_local + 1/cuota_visitante)
    posesion_local = _to_float(snap_actual["stats_local"].get("possessionPct", 50), 50)
    posesion_visitante = _to_float(snap_actual["stats_visitante"].get("possessionPct", 50), 50)
    if posesion_local + posesion_visitante ==0:
        return None
    prob_real_local = posesion_local / (posesion_local + posesion_visitante)
    ms = abs(prob_real_local - prob_esperada_local)

    if favorito_es_local:
        dominancia_pct, z = momentum.z_score_dominancia(
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "local"),
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "visitante"),
            momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "local"),
            momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "visitante"),
        )
    else:
        dominancia_pct, z = momentum.z_score_dominancia(
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "visitante"),
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "local"),
            momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "visitante"),
            momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "local"),
        )
    sd = min(abs(z) / 3, 1)

    minutos_dominando = 0
    for i in range(len(historial)-1, -1, -1):
        snap = historial[i]
        t_local = _to_float(snap.get("stats_local",{}).get("possessionPct", 50), 50)
        t_visitante = _to_float(snap.get("stats_visitante",{}).get("possessionPct", 50), 50)
        if favorito_es_local and t_local > t_visitante:
            minutos_dominando +=1
        elif not favorito_es_local and t_visitante > t_local:
            minutos_dominando +=1
        else:
            break
    tc = min(minutos_dominando / MINUTOS_MINIMOS_IDV, 1)

    tiros_local = _to_float(snap_actual["stats_local"].get("shotsOnTarget", 0), 0)
    tiros_visitante = _to_float(snap_actual["stats_visitante"].get("shotsOnTarget", 0), 0)
    if favorito_es_local:
        tiros_fav, tiros_riv = tiros_local, tiros_visitante
    else:
        tiros_fav, tiros_riv = tiros_visitante, tiros_local
    max_tiros = max(tiros_fav, 1)
    cf = (tiros_fav / max_tiros) * (1 - tiros_riv / max_tiros)

    idv = od * ms * sd * tc * cf * 100

    if idv >= UMBRAL_IDV_BAJO:
        equipo_domina = partido['local'] if favorito_es_local else partido['visitante']
        return {
            'idv': idv, 'equipo': equipo_domina, 'od': od, 'ms': ms,
            'sd': sd, 'tc': tc, 'cf': cf, 'z': z,
            'posesion_fav': posesion_local if favorito_es_local else posesion_visitante,
            'tiros_fav': tiros_fav, 'tiros_riv': tiros_riv,
            'cuota_fav': cuota_local if favorito_es_local else cuota_visitante,
        }
    return None


def _calcular_momentum_equipo(equipo, historial_snapshots, favorito_es_local):
    if not historial_snapshots or len(historial_snapshots) <2:
        return None
    puntos =0
    ultimos6 = historial_snapshots[-6:] if len(historial_snapshots) >=6 else historial_snapshots
    for i, snap in enumerate(ultimos6):
        peso = len(ultimos6) - i
        if favorito_es_local:
            gf = snap.get("goles_local",0)
            gc = snap.get("goles_visitante",0)
        else:
            gf = snap.get("goles_visitante",0)
            gc = snap.get("goles_local",0)
        if gf > gc:
            puntos += peso *1
        elif gf < gc:
            puntos += peso * -1
    return puntos


# =====================================================================
# UMBRAL PROGRESIVO POR DIFERENCIA DE GOLES (agosto 2026, a pedido
# explicito) -- SOLO para favorito_directo, y SOLO para el lado del
# favorito (el umbral del rival no cambia). Mientras mas ventaja tiene
# el favorito, mas dificil que dispare una alerta de "viene otro gol"
# -- cada alerta adicional aporta menos informacion nueva una vez que
# ya se sabe que domina y va ganando.
#
# Se basa en la DIFERENCIA neta actual (favorito - rival), no en el
# conteo absoluto de goles del favorito -- si el rival descuenta, la
# diferencia baja y el umbral vuelve a bajar con ella, sin memoria de
# lo estricto que llego a estar (confirmado a pedido explicito: 3-2 se
# trata igual que 1-0, ambos son diferencia +1).
#
# NOTA para revisiones futuras: se decidio A PROPOSITO mas estricto (no
# al reves, mas facil) mientras mas gana el favorito -- hay un
# argumento real en el sentido contrario (el equipo que pierde puede
# desmoronarse psicologicamente), pero se opto por no adivinar y en
# cambio dejar que cada alerta registre la diferencia de goles al
# momento de enviarse (ver _registrar_alerta) para poder revisar con
# evidencia real del Excel, dentro de unas semanas, si conviene
# invertir esta logica.
# =====================================================================
ESCALON_MAXIMO_UMBRAL = 2
INCREMENTO_POR_ESCALON = 0.4

# Multiplicadores de umbral por prioridad (a pedido explicito, agosto 2026)
# ALTA: z-score >= 1.7
# MEDIA: z-score >= 2.0
# BAJA: z-score >= 2.3
UMBRAL_Z_POR_PRIORIDAD = {
    "ALTA": 1.7,
    "MEDIA": 2.0,
    "BAJA": 2.3,
}


def _umbral_efectivo_favorito(partido, diferencia):
    prioridad = partido.get("prioridad", "ALTA")
    umbral_base = UMBRAL_Z_POR_PRIORIDAD.get(prioridad, 1.7)

    if partido.get("tipo_pronostico") == "favorito_directo":
        escalon = max(0, min(diferencia, ESCALON_MAXIMO_UMBRAL))
        umbral_base += (escalon * INCREMENTO_POR_ESCALON)

    return umbral_base


# =====================================================================
# CHEQUEO "SIGUEN EMPATADOS" (agosto 2026, a pedido explicito) -- red de
# seguridad por tiempo, SOLO para favorito_directo. En los minutos 22,
# 55 y 70, si el marcador sigue empatado, se pregunta con un chequeo
# BLANDO (solo que la presion del favorito sea mayor a la del rival,
# SIN exigir el umbral estadistico de z-score) si el favorito viene
# algo mejor. Su proposito es cubrir los casos donde hay una ventaja
# real pero nunca lo bastante clara como para que el sistema
# estadistico normal (z-score) la detectara por su cuenta.
#
# NUNCA duplica lo que el z-score ya avisó: si "posible_victoria_
# favorito" ya se mando en los ultimos VENTANA_ANTIDUP_CHEQUEO_EMPATE
# minutos, este chequeo se queda callado -- ya se avisó con mas
# certeza que lo que este chequeo blando podria aportar.
# =====================================================================
CHEQUEOS_EMPATE_MINUTOS = [22, 55, 70]
VENTANA_ANTIDUP_CHEQUEO_EMPATE = 25


def _cargar():
    if not ARCHIVO_PARTIDOS.exists():
        return None
    return json.loads(ARCHIVO_PARTIDOS.read_text(encoding="utf-8"))


def _guardar(datos):
    ARCHIVO_PARTIDOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def _en_ventana_horaria(partido):
    """Chequeo local, gratis: da margen razonable antes/despues del
    kickoff -- misma filosofia de siempre, nunca gastar una peticion
    si se puede evitar en frio."""
    try:
        inicio = datetime.datetime.fromisoformat(partido["kickoff_utc"].replace("Z", "+00:00"))
    except Exception:
        return True
    ahora = datetime.datetime.now(datetime.timezone.utc)
    minutos_desde_inicio = (ahora - inicio).total_seconds() / 60
    return -10 <= minutos_desde_inicio <= 130


def _registrar_alerta(partido, tipo, texto, minuto, diferencia_goles=None):
    partido.setdefault("alertas_enviadas", []).append({
        "tipo": tipo, "minuto": minuto, "texto": texto, "diferencia_goles": diferencia_goles,
    })


def _ya_se_envio_reciente(partido, tipo, minuto_actual, ventana=10):
    minuto_actual_int = momentum._minuto_a_entero(minuto_actual)
    for a in reversed(partido.get("alertas_enviadas", [])):
        if a["tipo"] != tipo:
            continue
        minuto_previo_int = momentum._minuto_a_entero(a["minuto"])
        if minuto_actual_int is None or minuto_previo_int is None:
            return True
        return abs(minuto_actual_int - minuto_previo_int) <= ventana
    return False


def _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival):
    """Calcula, para el favorito y el rival, la presion ponderada por
    tiempo (decide quien domina) y el conteo de eventos ponderado por
    tiempo (decide que tan confiable es esa lectura). Ver momentum.py."""
    presion_fav = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito)
    presion_riv = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival)
    n_fav = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_favorito)
    n_riv = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_rival)
    return presion_fav, presion_riv, n_fav, n_riv


def _evaluar_dominancia_general(partido, minuto_int, diferencia):
    """Devuelve (lado_ganador, dominancia_%, z) si algun lado supera el
    umbral de confianza, o None. lado_ganador es 'favorito' o 'rival'.
    El umbral del lado favorito escala con la diferencia de goles a su
    favor (ver _umbral_efectivo_favorito); el umbral del rival se
    mantiene fijo."""
    lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
    lado_rival = "visitante" if partido["favorito_es_local"] else "local"
    historial = partido.get("historial_snapshots", [])

    presion_fav, presion_riv, n_fav, n_riv = _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival)
    z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv)

    umbral_favorito = _umbral_efectivo_favorito(partido, diferencia)
    if z >= umbral_favorito:
        return "favorito", dominancia_fav, z
    if -z >= UMBRAL_Z_RIVAL:
        return "rival", 1 - dominancia_fav, -z
    return None


def _evaluar_dominancia_1er_tiempo(partido, minuto_int):
    """Mismo mecanismo que la general, pero con un umbral de confianza
    mas bajo (~80% en vez de ~90%) a proposito -- cubre 'algo se esta
    cocinando antes del descanso', no dominancia ya confirmada. Solo
    mira al favorito."""
    lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
    lado_rival = "visitante" if partido["favorito_es_local"] else "local"
    historial = partido.get("historial_snapshots", [])

    presion_fav, presion_riv, n_fav, n_riv = _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival)
    z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv)

    if z >= UMBRAL_Z_1ER_TIEMPO:
        return dominancia_fav, z
    return None


def _texto_alerta_favorito(diferencia, minuto_int, dominancia_pct, z, prioridad="ALTA"):
    conf = momentum.etiqueta_confianza(z)
    marca_prioridad = f" [{prioridad}]" if prioridad != "ALTA" else ""
    if diferencia <= 0 and minuto_int >= MINUTO_INICIO_CIERRE and z >= UMBRAL_Z_CIERRE:
        return "gol_de_cierre", f"\u23F0 Gol de cierre{marca_prioridad}"
    if minuto_int >= MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
        return None, None
    if diferencia < 0:
        return "posible_empate", f"\U0001F7E0 Gana Fav{marca_prioridad}"
    if diferencia == 0:
        return "posible_victoria_favorito", f"\U0001F7E2 Gana Fav{marca_prioridad}"
    if z >= 0:
        return "ampliacion_marcador", f"\U0001F535 Proximo gol: Fav{marca_prioridad}"
    return "ampliacion_marcador", f"\U0001F535 Proximo gol: No Fav{marca_prioridad}"


def _mensaje_idv(datos_idv, prioridad="MEDIA"):
    if datos_idv is None:
        return None, None
    idv = datos_idv['idv']
    if idv >= UMBRAL_IDV_ALTO:
        nivel = "\U0001F525 DESAFIO"
    elif idv >= UMBRAL_IDV_MEDIO:
        nivel = "\u26A0\uFE0F OJO"
    else:
        nivel = "\U0001F4A1 PISTA"
    marca_prioridad = f" [{prioridad}]" if prioridad != "ALTA" else ""
    texto = f"{nivel}{marca_prioridad}\n{datos_idv['equipo']} domina inesperado"
    return "value_alert", texto


def _evaluar_chequeo_empate(partido, minuto_int, snap_actual, historial):
    """Red de seguridad por tiempo -- ver comentario de las constantes
    CHEQUEOS_EMPATE_MINUTOS mas arriba."""
    if partido.get("tipo_pronostico") != "favorito_directo":
        return None
    if snap_actual["goles_local"] != snap_actual["goles_visitante"]:
        return None  # no esta empatado, no aplica

    for i, checkpoint in enumerate(CHEQUEOS_EMPATE_MINUTOS):
        limite_superior = CHEQUEOS_EMPATE_MINUTOS[i + 1] if i + 1 < len(CHEQUEOS_EMPATE_MINUTOS) else 200
        if not (checkpoint <= minuto_int < limite_superior):
            continue

        tipo_chequeo = f"siguen_empatados_{checkpoint}"
        if _ya_se_envio_reciente(partido, tipo_chequeo, minuto_int, ventana=999):
            return None  # este checkpoint ya se resolvio (se mando una vez)

        # Red de seguridad: si el z-score ya avisó de esto, no duplicar
        if _ya_se_envio_reciente(partido, "posible_victoria_favorito", minuto_int, ventana=VENTANA_ANTIDUP_CHEQUEO_EMPATE):
            return None

        # Chequeo BLANDO: basta con que el favorito tenga alguna ventaja
        # de presion, sin exigir el umbral estadistico de z-score
        lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
        lado_rival = "visitante" if partido["favorito_es_local"] else "local"
        presion_fav = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito)
        presion_riv = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival)
        if presion_fav <= presion_riv:
            return None  # sin ventaja todavia -- se reintenta en el siguiente ciclo, dentro de la misma franja

        return tipo_chequeo, f"\u23F1\uFE0F Siguen empatados (min {checkpoint}+) -- {escapar_html(partido['favorito'])} con ligera ventaja."

    return None


def _evaluar_alertas(partido, snap_actual, snap_anterior, minuto):
    favorito_es_local = partido["favorito_es_local"]
    gl, gv = snap_actual["goles_local"], snap_actual["goles_visitante"]
    goles_favorito = gl if favorito_es_local else gv
    goles_rival = gv if favorito_es_local else gl
    diferencia = goles_favorito - goles_rival

    lado_favorito = "local" if favorito_es_local else "visitante"
    lado_rival = "visitante" if favorito_es_local else "local"

    # --- Eventos discretos: inmediatos, sin filtro de minuto minimo ---
    if momentum.hubo_tarjeta_roja(snap_actual, snap_anterior, lado_rival):
        if not _ya_se_envio_reciente(partido, "tarjeta_roja", minuto, ventana=999):
            equipo = partido['visitante'] if lado_rival == "visitante" else partido['local']
            return [("tarjeta_roja", f"\U0001F7E5 Tarjeta roja para {equipo}.")]
    if momentum.hubo_tarjeta_roja(snap_actual, snap_anterior, lado_favorito):
        if not _ya_se_envio_reciente(partido, "tarjeta_roja", minuto, ventana=999):
            equipo = partido['local'] if lado_favorito == "local" else partido['visitante']
            return [("tarjeta_roja", f"\U0001F7E5 Tarjeta roja para {equipo}.")]

    if momentum.hubo_penal(snap_actual, snap_anterior, lado_favorito):
        if not _ya_se_envio_reciente(partido, "penal", minuto, ventana=15):
            equipo = partido['local'] if lado_favorito == "local" else partido['visitante']
            return [("penal", f"\U0001F3AF Penal para {equipo}.")]
    if momentum.hubo_penal(snap_actual, snap_anterior, lado_rival):
        if not _ya_se_envio_reciente(partido, "penal", minuto, ventana=15):
            equipo = partido['visitante'] if lado_rival == "visitante" else partido['local']
            return [("penal", f"\U0001F3AF Penal para {equipo}.")]

    minuto_int = momentum._minuto_a_entero(minuto) or 45
    if minuto_int < MINUTO_MINIMO_ALERTA_MOMENTUM:
        return []

    # --- Alerta de primer tiempo: ventana y umbral propios, mas suave ---
    if gl == 0 and gv == 0 and MINUTO_INICIO_1ER_TIEMPO <= minuto_int <= MINUTO_FIN_1ER_TIEMPO:
        score_1t = _evaluar_dominancia_1er_tiempo(partido, minuto_int)
        if score_1t is not None and not _ya_se_envio_reciente(partido, "alerta_1er_tiempo", minuto_int, ventana=999):
            return [("alerta_1er_tiempo",
                      f"\u23F1\uFE0F Alerta de primer tiempo -- el favorito domina el 0-0 ({round(score_1t*100)}%).")]

    # --- Dominancia general (decaimiento exponencial + z-score), favorito o rival ---
    resultado = _evaluar_dominancia_general(partido, minuto_int, diferencia)
    if resultado:
        lado_resultado, dominancia_pct, z = resultado
        prioridad = partido.get("prioridad", "ALTA")
        if lado_resultado == "favorito":
            tipo, texto = _texto_alerta_favorito(diferencia, minuto_int, dominancia_pct, z, prioridad)
        else:
            tipo = None
            texto = None
            if minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
                tipo = "cuidado_rival_presiona"
                conf = momentum.etiqueta_confianza(z)
                marca_prioridad = f" [{prioridad}]" if prioridad != "ALTA" else ""
                texto = f"\u26A0\uFE0F Rival domina{marca_prioridad}"
        if tipo and not _ya_se_envio_reciente(partido, tipo, minuto_int):
            return [(tipo, texto)]

    # --- IDV: Alerta de VALUE en partidos con cuotas parejas ---
    historial = partido.get("historial_snapshots", [])
    prioridad = partido.get("prioridad", "ALTA")
    if minuto_int >= MINUTOS_MINIMOS_IDV and minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
        datos_idv = _calcular_idv(partido, snap_actual, historial, minuto_int)
        if datos_idv and not _ya_se_envio_reciente(partido, "value_alert", minuto_int, ventana=30):
            tipo_idv, texto_idv = _mensaje_idv(datos_idv, prioridad)
            if tipo_idv:
                return [(tipo_idv, texto_idv)]

    # --- Chequeo "siguen empatados" (red de seguridad por tiempo) ---
    resultado_chequeo = _evaluar_chequeo_empate(partido, minuto_int, snap_actual, historial)
    if resultado_chequeo:
        return [resultado_chequeo]

    return []


def _mensaje_partido(partido, minuto, snap_actual, texto, dominancia_fav=None, z=None):
    """
    AMPLIADO a pedido explicito: antes solo mostraba tiros a puerta y
    posesion -- insuficiente para que la persona juzgue por si misma si
    de verdad hay ataque real o paridad. Ahora trae TODOS los numeros
    crudos que ya usa el calculo de momentum (no solo la conclusion),
    para que el criterio final sea del usuario, no solo del sistema.

    CORREGIDO (agosto 2026, a pedido explicito): TODO el mensaje
    respeta siempre el orden local -> visitante, sin excepcion; el
    favorito se marca unicamente con la corona junto a su nombre, nunca
    reordenando quien va primero.

    REESTRUCTURADO de nuevo (agosto 2026, a pedido explicito):
      - El titulo "Alertas Excel" ya no va aqui -- telegram_utils.py lo
        antepone automaticamente a CUALQUIER mensaje que se envie (ver
        NOMBRE_PROYECTO), asi que no hace falta repetirlo.
      - Orden del mensaje: (1) tipo de alerta, (2) estadisticas
        acumuladas -- tiros a puerta, tiros totales, corners, tiros
        bloqueados, posesion, faltas, y la confianza estadistica como
        ULTIMA linea de ese mismo bloque (ya no es una seccion aparte),
        (3) datos del enfrentamiento (equipos, marcador, favorito,
        cuota inicial) al final, como referencia.
      - El emoji de tipo de pronostico (🎯/🔀) ahora va PEGADO a la
        corona (ej. "🎯👑"), junto al nombre del equipo favorito -- ya
        no antecede a toda la linea del titulo.
      - "Faltas" = faltas que ESE equipo cometio (foulsCommitted de
        ESPN), no las que recibio.
    """
    fav_local = partido["favorito_es_local"]
    emoji_tipo = EMOJI_TIPO_PRONOSTICO.get(partido.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
    marca_favorito = f" {emoji_tipo}{CORONA_FAVORITO}"
    corona_local = marca_favorito if fav_local else ""
    corona_visitante = marca_favorito if not fav_local else ""

    stats_local = snap_actual["stats_local"]
    stats_visitante = snap_actual["stats_visitante"]

    def _n(stats, campo):
        return stats.get(campo, "?")

    gl = snap_actual['goles_local']
    gv = snap_actual['goles_visitante']

    cuota_l = partido.get("cuota_local_inicial")
    cuota_x = partido.get("cuota_empate_inicial")
    cuota_v = partido.get("cuota_visitante_inicial")
    partes_cuota = []
    if cuota_l:
        partes_cuota.append(f"{cuota_l}")
    if cuota_x:
        partes_cuota.append(f"{cuota_x}")
    if cuota_v:
        partes_cuota.append(f"{cuota_v}")
    cuota_str = " | ".join(partes_cuota) if partes_cuota else ""

    def _fila(nombre, val_local, val_visitante):
        return f"{nombre:<18}{str(val_local):>7}{str(val_visitante):>7}"

    tabla = "<pre>"
    tabla += "                  Local  Visit\n"
    tabla += "---------------- ------ ------\n"
    tabla += _fila("Tiros a puerta", _n(stats_local,'shotsOnTarget'), _n(stats_visitante,'shotsOnTarget')) + "\n"
    tabla += _fila("Tiros totales", _n(stats_local,'totalShots'), _n(stats_visitante,'totalShots')) + "\n"
    tabla += _fila("Corners", _n(stats_local,'wonCorners'), _n(stats_visitante,'wonCorners')) + "\n"
    tabla += _fila("Tiros bloqueados", _n(stats_local,'blockedShots'), _n(stats_visitante,'blockedShots')) + "\n"
    tabla += _fila("Posesion", f"{_n(stats_local,'possessionPct')}%", f"{_n(stats_visitante,'possessionPct')}%") + "\n"
    tabla += _fila("Faltas", _n(stats_local,'foulsCommitted'), _n(stats_visitante,'foulsCommitted')) + "\n"
    tabla += "</pre>"

    lineas = [f"<b>{texto}</b>"]
    lineas.append(f"{escapar_html(partido['local'])}{corona_local} <b>{gl} - {gv}</b> {escapar_html(partido['visitante'])}{corona_visitante}")
    if cuota_str:
        lineas.append(f"Cuotas: {cuota_str} | Min {minuto}")
    lineas.append(tabla)

    if dominancia_fav is not None and z is not None:
        conf = momentum.etiqueta_confianza(z)
        lado_domina = partido['favorito'] if z >= 0 else partido['no_favorito']
        dominancia_mostrada = dominancia_fav if z >= 0 else (1 - dominancia_fav)
        lineas.append(f"⚡ {conf} ({round(dominancia_mostrada*100)}% {escapar_html(lado_domina)}, z={z:.1f})")

    historial_momentum = partido.get("historial_snapshots", [])
    if len(historial_momentum) >=2:
        momentum_local = _calcular_momentum_equipo("local", historial_momentum, True)
        momentum_visitante = _calcular_momentum_equipo("visitante", historial_momentum, False)
        if momentum_local is not None and momentum_visitante is not None:
            lineas.append(f"\U0001F4C8 Forma: {escapar_html(partido['local'])} {momentum_local:+d} | {escapar_html(partido['visitante'])} {momentum_visitante:+d}")

    if "value" in texto.lower() or "VALUE" in texto:
        historial = partido.get("historial_snapshots", [])
        datos_idv = _calcular_idv(partido, snap_actual, historial, momentum._minuto_a_entero(minuto) or 0)
        if datos_idv:
            lineas.append(f"\U0001F4CA IDV: {round(datos_idv['idv'],1)} | OD:{round(datos_idv['od'],3)} MS:{round(datos_idv['ms'],3)} SD:{round(datos_idv['sd'],3)} TC:{round(datos_idv['tc'],3)} CF:{round(datos_idv['cf'],3)}")
            lineas.append(f"\U0001F4B0 Cuota fav: {datos_idv['cuota_fav']} | Posesion: {round(datos_idv['posesion_fav'])}% | Tiros: {datos_idv['tiros_fav']}-{datos_idv['tiros_riv']} | z={datos_idv['z']:.1f}")

    local_besoccer = partido['local'].replace(' ', '+')
    visitante_besoccer = partido['visitante'].replace(' ', '+')
    fecha_partido = partido.get('hora_inicio', '')[:10] if partido.get('hora_inicio') else ''
    year = fecha_partido[:4] if fecha_partido else ''
    mes = fecha_partido[5:7] if fecha_partido else ''
    dia = fecha_partido[8:10] if fecha_partido else ''

    keyboard = [[
        {"text": "⚽ BeSoccer", "url": f"https://www.besoccer.com/buscar?q={local_besoccer.replace('+', '%20')}+{visitante_besoccer.replace('+', '%20')}"},
        {"text": "🎰 1xBet", "url": f"https://www.1xbet.com/en/search?q={local_besoccer.replace('+', '%20')}+vs+{visitante_besoccer.replace('+', '%20')}"},
    ],[
        {"text": "📊 SofaScore", "url": f"https://www.sofascore.com/search?q={local_besoccer.replace('+', '%20')}%20{visitante_besoccer.replace('+', '%20')}"},
        {"text": "⚡ Flashscore", "url": f"https://www.flashscore.com/search/?q={local_besoccer.replace('+', '%20')}+{visitante_besoccer.replace('+', '%20')}"},
    ]]
    reply_markup = {"inline_keyboard": keyboard}

    return "\n".join(lineas), reply_markup


def _mensaje_partido_finalizado(partido, gh, gv):
    """
    NUEVO (agosto 2026, a pedido explicito) -- aviso INMEDIATO cuando
    ESPN marca el partido como terminado, sin esperar al reporte de las
    6am del dia siguiente. Ya incluye si el pronostico acerto o no,
    usando el mismo criterio que cerrar_resultados.py (calcular_acierto
    compartido -- una sola fuente de verdad, para que este aviso en
    vivo y la auditoria nocturna nunca queden desincronizados).
    """
    acierto = calcular_acierto(partido, gh, gv)
    marca = "\u2705 Acierto" if acierto else "\u274C Fallo"

    fav_local = partido["favorito_es_local"]
    emoji_tipo = EMOJI_TIPO_PRONOSTICO.get(partido.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
    marca_favorito = f" {emoji_tipo}{CORONA_FAVORITO}"
    corona_local = marca_favorito if fav_local else ""
    corona_visitante = marca_favorito if not fav_local else ""
    titulo = (
        f"<b>{escapar_html(partido['local'])}{corona_local}</b> vs "
        f"<b>{escapar_html(partido['visitante'])}{corona_visitante}</b>"
    )

    lineas = [
        "\U0001F3C1 Partido finalizado",
        "",
        f"{titulo}",
        f"Resultado final: {gh}-{gv}",
        f"Favorito: {escapar_html(partido['favorito'])}",
        f"{marca}",
    ]
    return "\n".join(lineas)


def vigilar():
    datos = _cargar()
    if not datos:
        print("No hay partidos_hoy.json todavia. Se reintentara en el proximo ciclo.")
        return

    hubo_cambios = False
    for partido in datos["partidos"]:
        # NUEVO: una vez que se manda el aviso de finalizado, ya no se
        # vuelve a consultar este partido en NINGUN ciclo posterior --
        # ahorro de peticiones (ya no tiene sentido seguir gastando
        # cupo de ESPN en un partido que ya termino). 'acierto' NO se
        # toca aqui a proposito -- eso lo sigue decidiendo
        # cerrar_resultados.py esa noche, con su propio flujo completo
        # (rating propio Glicko-2 + auditoria de cada alerta
        # individual), sin interferencia de este aviso en vivo.
        if partido.get("aviso_final_enviado") or not partido.get("fixture_id"):
            continue
        if not _en_ventana_horaria(partido):
            continue

        liga_slug = partido.get("liga_slug")
        if not liga_slug:
            print(f"[AVISO] {partido['partido']} no tiene liga_slug guardado, no se puede vigilar.")
            continue

        box = obtener_boxscore_en_vivo(liga_slug, partido["fixture_id"])
        if box is None:
            continue

        if box.get("estado") == "post":
            mensaje = _mensaje_partido_finalizado(partido, box["goles_local"], box["goles_visitante"])
            if enviar_mensaje_telegram(mensaje):
                partido["aviso_final_enviado"] = True
                hubo_cambios = True
            continue

        if box.get("estado") != "in":
            continue

        snap_actual = {
            "minuto": box["minuto"], "goles_local": box["goles_local"],
            "goles_visitante": box["goles_visitante"],
            "stats_local": box["stats_local"], "stats_visitante": box["stats_visitante"],
        }
        historial = partido.setdefault("historial_snapshots", [])
        snap_anterior = historial[-1] if historial else None
        historial.append(snap_actual)
        hubo_cambios = True

        favorito_es_local = partido["favorito_es_local"]
        goles_favorito = box["goles_local"] if favorito_es_local else box["goles_visitante"]
        goles_rival = box["goles_visitante"] if favorito_es_local else box["goles_local"]
        diferencia_actual = goles_favorito - goles_rival

        alertas = _evaluar_alertas(partido, snap_actual, snap_anterior, box["minuto"])
        if alertas:
            lado_favorito = "local" if favorito_es_local else "visitante"
            lado_rival = "visitante" if favorito_es_local else "local"
            presion_fav, presion_riv, n_fav, n_riv = _presiones_y_eventos(historial, box["minuto"], lado_favorito, lado_rival)
            z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv)

        for tipo, texto in alertas:
            mensaje, reply_markup = _mensaje_partido(partido, box["minuto"], snap_actual, texto,
                                        dominancia_fav=dominancia_fav, z=z)
            if enviar_mensaje_telegram(mensaje, reply_markup=reply_markup):
                _registrar_alerta(partido, tipo, texto, box["minuto"], diferencia_goles=diferencia_actual)

    if hubo_cambios:
        _guardar(datos)


if __name__ == "__main__":
    vigilar()

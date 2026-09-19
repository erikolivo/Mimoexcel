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
import traceback
from pathlib import Path

from fetch_data import obtener_boxscore_en_vivo, obtener_estado_desde_scoreboard, obtener_historial_equipo
from telegram_utils import enviar_mensaje_telegram, escapar_html
from cerrar_resultados import calcular_acierto
from resolucion_alertas import (
    CRITERIO_POR_TIPO,
    resolver_pendientes,
    mensaje_resolucion,
    tiene_trabajo_pendiente,
    linea_efectividad,
)
from resumen import _calcular_nivel_actual
import momentum

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_PARTIDOS = DATA_DIR / "partidos_hoy.json"

MINUTO_INICIO_CIERRE = 75
MAXIMO_MINUTO_ALERTAS_NO_CIERRE = 75

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

UMBRAL_Z_ALERTA = 1.65                              # z-score para Gana Fav (empate o perdiendo <2 goles) — bajado con Kish
UMBRAL_Z_CIERRE = 3.2                            # C6/Fase B (antes 2.3)
UMBRAL_Z_RIVAL = 2.0                             # C4/Fase B: rival domina (antes 1.8)
UMBRAL_Z_1ER_TIEMPO = 1.3                               # z-score para alerta de primer tiempo — bajado con Kish
MINUTO_INICIO_1ER_TIEMPO = 15
MINUTO_FIN_1ER_TIEMPO = 30                          # C5/Fase B (antes 40)

# =====================================================================
# IDV - INDICE DE DESVIACION DE VALOR (agosto 2026)
# Detecta cuando un equipo domina en partidos con cuotas parejas
# =====================================================================

UMBRAL_IDV_BAJO = 2
UMBRAL_IDV_MEDIO = 5
UMBRAL_IDV_ALTO = 10
MINUTOS_MINIMOS_IDV = 5

# --- Nuevas alertas de valor (septiembre 2026) ---
UMBRAL_Z_FAV_NO_GANA = 1.5       # favorito dominando pero empatando/perdiendo
UMBRAL_Z_NO_FAV_DOMINA = 1.5     # no-favorito dominando claramente
UMBRAL_CUOTA_FAVORITO = 2.0      # cuota para ser considerado "favorito"
MINUTOS_MINIMOS_VALOR = 15       # minutos minimos para ambas alertas
DIFERENCIA_CUOTAS_MINIMA = 1.0   # diferencia minima entre cuotas para alerta de favorito


# =====================================================================
# CONFIG_ALERTAS (mejoras 2026-09) -- todo cambio de comportamiento va
# detras de una constante de este bloque, para poder apagarlo sin tocar
# logica. Fase A cablea solo resolucion/mensajes; los flags de EMISION
# (ALERTA_ACTIVA, PRESION_MIN_*, umbrales) se cablean en Fase B y la
# ventana en Fase C (F2).
# =====================================================================

SIN_GOL_ES_FALLO = True
RESOLUCION_MODO = "individual"        # "individual" | "resumen_final"
VENTANA_MAX_MINUTOS = 240             # F2/Fase C (hoy _en_ventana_horaria usa 130)

ALERTA_ACTIVA = {
    "posible_victoria_favorito": True,
    "posible_descuento": True,
    "ampliacion_marcador": True,
    "cuidado_rival_presiona": True,
    "alerta_1er_tiempo": True,
    "gol_de_cierre": True,
    "fav_domina_no_gana": True,
    "no_fav_domina": True,
    "value_alert": False,             # C9/Fase B
    "siguen_empatados": True,
    "cambio_momentum": False,         # C11/Fase B
    "tarjeta_roja": True,
}

PRESION_MIN_VICTORIA = 8.0            # C1/Fase B
PRESION_MIN_AMPLIACION = 11.0         # C3/Fase B
PRESION_MIN_NO_FAV = 11.0             # C8/Fase B

DESCUENTO_MAX_MINUTO = 60                       # C2/Fase B
DESCUENTO_SOLO_FAVORITO_DIRECTO = True          # C2/Fase B

# cuidado_rival_presiona (C4)
RIVAL_TIROS_PUERTA_MIN = 2
VENTANA_RIVAL_MINUTOS = 15

# alerta_1er_tiempo (C5)
PRIMER_TIEMPO_SOLO_FAVORITO_DIRECTO = True

# gol_de_cierre (C6)
CIERRE_MAX_MINUTO = 84
CIERRE_DIFS_PERMITIDAS = (-1, 0)

FAV_NO_GANA_MAX_DEFICIT = 2                     # C7/Fase B
NO_FAV_DIF_MIN = 0                              # C8/Fase B


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
        n_local, sq_local = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "local")
        n_visitante, sq_visitante = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "visitante")
        z, dominancia_pct = momentum.z_score_dominancia(
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "local"),
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "visitante"),
            n_local, n_visitante, sq_local, sq_visitante,
        )
    else:
        n_local, sq_local = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "local")
        n_visitante, sq_visitante = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, "visitante")
        z, dominancia_pct = momentum.z_score_dominancia(
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "visitante"),
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, "local"),
            n_visitante, n_local, sq_visitante, sq_local,
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


def _evaluar_fav_domina_no_gana(partido, snap_actual, historial, minuto_int):
    """Detecta cuando el favorito domina estadisticamente pero esta
    empatando o perdiendo. Significa que las cuotas en vivo estan
    infladas (dan mas valor del que deberia tener el favorito)."""
    cuota_local = partido.get("cuota_local_inicial")
    cuota_visitante = partido.get("cuota_visitante_inicial")
    if not cuota_local or not cuota_visitante or cuota_local <= 0 or cuota_visitante <= 0:
        return None

    favorito_es_local = partido["favorito_es_local"]
    gl, gv = snap_actual["goles_local"], snap_actual["goles_visitante"]

    if favorito_es_local:
        diferencia = gl - gv
        cuota_fav = cuota_local
        cuota_riv = cuota_visitante
    else:
        diferencia = gv - gl
        cuota_fav = cuota_visitante
        cuota_riv = cuota_local

    if cuota_fav >= UMBRAL_CUOTA_FAVORITO:
        return None
    if abs(cuota_local - cuota_visitante) < DIFERENCIA_CUOTAS_MINIMA:
        return None
    if diferencia > 0:
        return None
    if diferencia < -FAV_NO_GANA_MAX_DEFICIT:  # C7: tope de deficit
        return None
    if minuto_int < MINUTOS_MINIMOS_VALOR:
        return None

    lado_fav = "local" if favorito_es_local else "visitante"
    lado_riv = "visitante" if favorito_es_local else "local"
    n_fav, sq_fav = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_fav)
    n_riv, sq_riv = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_riv)
    z, dominancia_fav = momentum.z_score_dominancia(
        momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_fav),
        momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_riv),
        n_fav, n_riv, sq_fav, sq_riv,
    )

    if z < UMBRAL_Z_FAV_NO_GANA:
        return None

    equipo_fav = partido['local'] if favorito_es_local else partido['visitante']
    tiros_fav = _to_float(snap_actual[f"stats_{lado_fav}"].get("shotsOnTarget", 0), 0)
    tiros_riv = _to_float(snap_actual[f"stats_{lado_riv}"].get("shotsOnTarget", 0), 0)
    posesion_fav = _to_float(snap_actual[f"stats_{lado_fav}"].get("possessionPct", 50), 50)

    if diferencia == 0:
        texto_score = "Empate"
    else:
        texto_score = f"Perdiendo {gl}-{gv}"

    conf = momentum.etiqueta_confianza(z)
    nivel = f"{conf} | IDV: {_nivel_idv_basico(z)}"
    texto = (
        f"\U0001F526 FAVORITO DOMINA\n"
        f"{equipo_fav} {texto_score}\n"
        f"z: {z:.1f} | Tiros: {tiros_fav}-{tiros_riv}\n"
        f"Posesi\u00f3n: {posesion_fav:.0f}%\n"
        f"Cuota pre: {cuota_fav:.2f} -> en vivo deber\u00eda bajar"
    )
    return "fav_domina_no_gana", texto


def _evaluar_no_favorito_domina(partido, snap_actual, historial, minuto_int):
    """Detecta cuando el no-favorito domina estadisticamente.
    Significa que el mercado se equivoco, el 'perdedor' esta jugando mejor."""
    cuota_local = partido.get("cuota_local_inicial")
    cuota_visitante = partido.get("cuota_visitante_inicial")
    if not cuota_local or not cuota_visitante or cuota_local <= 0 or cuota_visitante <= 0:
        return None

    favorito_es_local = partido["favorito_es_local"]
    gl, gv = snap_actual["goles_local"], snap_actual["goles_visitante"]

    if favorito_es_local:
        cuota_no_fav = cuota_visitante
        lado_no_fav = "visitante"
        lado_fav = "local"
        diferencia = gl - gv
    else:
        cuota_no_fav = cuota_local
        lado_no_fav = "local"
        lado_fav = "visitante"
        diferencia = gv - gl

    if cuota_no_fav <= UMBRAL_CUOTA_FAVORITO:
        return None
    if minuto_int < MINUTOS_MINIMOS_VALOR:
        return None
    if diferencia < NO_FAV_DIF_MIN:  # C8: no enviar si el no-favorito ya va ganando
        return None

    n_no_fav, sq_no_fav = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_no_fav)
    n_fav, sq_fav = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_fav)
    presion_no_fav = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_no_fav)
    z, dominancia_fav = momentum.z_score_dominancia(
        presion_no_fav,
        momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_fav),
        n_no_fav, n_fav, sq_no_fav, sq_fav,
    )

    if z < UMBRAL_Z_NO_FAV_DOMINA:
        return None
    if presion_no_fav < PRESION_MIN_NO_FAV:  # C8: presion minima del no-favorito
        return None

    equipo_no_fav = partido['local'] if not favorito_es_local else partido['visitante']
    tiros_no_fav = _to_float(snap_actual[f"stats_{lado_no_fav}"].get("shotsOnTarget", 0), 0)
    tiros_fav = _to_float(snap_actual[f"stats_{lado_fav}"].get("shotsOnTarget", 0), 0)
    posesion_no_fav = _to_float(snap_actual[f"stats_{lado_no_fav}"].get("possessionPct", 50), 50)

    gl_no_fav = gv if not favorito_es_local else gl
    gl_fav = gl if not favorito_es_local else gv

    conf = momentum.etiqueta_confianza(z)
    nivel = f"{conf} | IDV: {_nivel_idv_basico(z)}"
    texto = (
        f"\U0001F4CA MERCADO SE EQUIVOCO\n"
        f"{equipo_no_fav} domina (cuota {cuota_no_fav:.2f})\n"
        f"z: {z:.1f} | Tiros: {tiros_no_fav}-{tiros_fav}\n"
        f"Posesi\u00f3n: {posesion_no_fav:.0f}%\n"
        f"Marcador: {gl}-{gv}"
    )
    return "no_fav_domina", texto


def _nivel_idv_basico(z):
    """Nivel IDV basico para alertas de valor (sin calcular IDV completo)."""
    z_abs = abs(z)
    if z_abs >= 3:
        return "ALTO"
    elif z_abs >= 2:
        return "MEDIO"
    else:
        return "BAJO"


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
    "ALTA": 1.4,    # bajado con Kish
    "MEDIA": 1.7,   # bajado con Kish
    "BAJA": 2.0,    # bajado con Kish
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
    # Defensa: nunca escribir un dict que no sea el archivo completo
    # (un shadowing de variable una vez sobrescribio partidos_hoy.json
    # con un registro de prediccion y cego a Fase 3 por horas).
    if not isinstance(datos, dict) or "partidos" not in datos:
        print(f"[ERROR] _guardar rechazo escritura: datos sin 'partidos' (keys={list(datos.keys()) if isinstance(datos, dict) else type(datos)}).")
        return
    datos["predicciones_activas"] = PREDICCIONES_ACTIVAS
    datos["historial_predicciones"] = HISTORIAL_PREDICCIONES
    ARCHIVO_PARTIDOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


# =====================================================================
# SISTEMA DE PREDICCIONES Y EFECTIVIDAD
# =====================================================================

PREDICCIONES_ACTIVAS = {}  # {partido_id: {tipo: {minuto, prediccion, equipo}}}
HISTORIAL_PREDICCIONES = {}  # {tipo: {total: N, aciertos: N}}

TIPOS_PREDICCION_FAV = [
    "gol_de_cierre", "posible_victoria_favorito", "posible_empate",
    "ampliacion_marcador", "alerta_1er_tiempo", "value_alert",
    "siguen_empatados", "cambio_momentum"
]

TIPOS_PREDICCION_RIVAL = ["cuidado_rival_presiona"]


def _registrar_prediccion(partido_id, tipo, minuto, prediccion, equipo):
    if partido_id not in PREDICCIONES_ACTIVAS:
        PREDICCIONES_ACTIVAS[partido_id] = {}
    PREDICCIONES_ACTIVAS[partido_id][tipo] = {
        "minuto": minuto,
        "prediccion": prediccion,
        "equipo": equipo,
    }


def _verificar_predicciones(partido_id, goles_local_nuevos, goles_visitante_nuevos,
                             goles_local_anteriores, goles_visitante_anteriores,
                             favorito_es_local):
    if partido_id not in PREDICCIONES_ACTIVAS:
        return []
    
    resultados = []
    predicciones = PREDICCIONES_ACTIVAS[partido_id].copy()
    
    nuevo_gol_local = goles_local_nuevos > goles_local_anteriores
    nuevo_gol_visitante = goles_visitante_nuevos > goles_visitante_anteriores
    
    for tipo, datos in predicciones.items():
        equipo_prediccion = datos["prediccion"]
        
        if favorito_es_local:
            marco_favorito = nuevo_gol_local
            marco_rival = nuevo_gol_visitante
        else:
            marco_favorito = nuevo_gol_visitante
            marco_rival = nuevo_gol_local
        
        if equipo_prediccion == "fav":
            acierto = marco_favorito
        else:
            acierto = marco_rival
        
        resultados.append((tipo, acierto, datos))
        if tipo not in HISTORIAL_PREDICCIONES:
            HISTORIAL_PREDICCIONES[tipo] = {"total": 0, "aciertos": 0}
        HISTORIAL_PREDICCIONES[tipo]["total"] += 1
        if acierto:
            HISTORIAL_PREDICCIONES[tipo]["aciertos"] += 1
        del PREDICCIONES_ACTIVAS[partido_id][tipo]
    
    return resultados


def _calcular_efectividad(tipo_alerta):
    if tipo_alerta not in HISTORIAL_PREDICCIONES:
        return 0, 0, 0
    datos = HISTORIAL_PREDICCIONES[tipo_alerta]
    total = datos["total"]
    aciertos = datos["aciertos"]
    if total == 0:
        return 0, 0, 0
    return total, aciertos, round((aciertos / total) * 100)


def _mensaje_efectividad(tipo_alerta):
    total, aciertos, porcentaje = _calcular_efectividad(tipo_alerta)
    if total == 0:
        return ""
    return f"📊 Efectividad hoy: {porcentaje}% ({aciertos}/{total} aciertos)"


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
    return -10 <= minutos_desde_inicio <= VENTANA_MAX_MINUTOS


def _registrar_alerta(partido, tipo, texto, minuto, diferencia_goles=None, marcador=None):
    """Registra el envio de una alerta con los campos del modelo R1
    (compatibles hacia atras: los antiguos solo tenian los 4 primeros).
    Ya no alimenta el sistema viejo de PREDICCIONES (R1): la resolucion
    se hace sobre estas mismas alertas."""
    alertas = partido.setdefault("alertas_enviadas", [])
    lado, criterio = CRITERIO_POR_TIPO.get(tipo, (None, None))
    minuto_int = momentum._minuto_a_entero(minuto)
    fid = partido.get("fixture_id", "?")
    alertas.append({
        "tipo": tipo, "minuto": minuto, "texto": texto, "diferencia_goles": diferencia_goles,
        "id": f"{fid}-{len(alertas)}",
        "minuto_int": minuto_int,
        "marcador_alerta": list(marcador) if marcador else None,
        "lado": lado, "criterio": criterio,
        "estado": "pendiente" if criterio else "no_aplica",
        "resuelta_minuto": None, "resuelta_motivo": None,
        "resolucion_notificada": True if criterio is None else False,
        "acierto": None,
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
    """Calcula presion ponderada y eventos ponderados (con suma de pesos^2 para Kish)."""
    presion_fav = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito)
    presion_riv = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival)
    n_fav, sq_fav = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_favorito)
    n_riv, sq_riv = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_rival)
    return presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv


def _evaluar_dominancia_general(partido, minuto_int, diferencia):
    """Devuelve (lado_ganador, dominancia_%, z, presion_fav, presion_riv)
    si algun lado supera el umbral de confianza, o None. lado_ganador es
    'favorito' o 'rival'. El umbral del lado favorito escala con la
    diferencia de goles a su favor (ver _umbral_efectivo_favorito); el
    umbral del rival se mantiene fijo."""
    lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
    lado_rival = "visitante" if partido["favorito_es_local"] else "local"
    historial = partido.get("historial_snapshots", [])

    presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv = _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival)
    z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv)

    umbral_favorito = _umbral_efectivo_favorito(partido, diferencia)
    if z >= umbral_favorito:
        return "favorito", dominancia_fav, z, presion_fav, presion_riv
    if -z >= UMBRAL_Z_RIVAL:
        return "rival", 1 - dominancia_fav, -z, presion_fav, presion_riv
    return None


def _evaluar_dominancia_1er_tiempo(partido, minuto_int):
    """Mismo mecanismo que la general, pero con un umbral de confianza
    mas bajo (~80% en vez de ~90%) a proposito -- cubre 'algo se esta
    cocinando antes del descanso', no dominancia ya confirmada. Solo
    mira al favorito."""
    lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
    lado_rival = "visitante" if partido["favorito_es_local"] else "local"
    historial = partido.get("historial_snapshots", [])

    presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv = _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival)
    z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv)

    if z >= UMBRAL_Z_1ER_TIEMPO:
        return dominancia_fav, z
    return None


def _texto_alerta_favorito(diferencia, minuto_int, dominancia_pct, z, prioridad="ALTA",
                           presion_fav=0.0, tipo_pronostico="favorito_directo"):
    """Texto (y tipo) de alerta del favorito segun marcador. Reglas
    C1/C2/C3/C6 (Fase B): cada rama exige su filtro; si no cumple,
    (None, None) -- nunca se "degrada" a otra alerta."""
    conf = momentum.etiqueta_confianza(z)
    marca_prioridad = f" [{prioridad}]" if prioridad != "ALTA" else ""
    if minuto_int >= MINUTO_INICIO_CIERRE:
        # C6: cierre SOLO con dif -1/0, min<=84 y z>=3.2. Pasado el 75',
        # si no es cierre no cae a ninguna otra alerta (igual que hoy).
        if diferencia in CIERRE_DIFS_PERMITIDAS and minuto_int <= CIERRE_MAX_MINUTO \
                and z >= UMBRAL_Z_CIERRE:
            return "gol_de_cierre", f"\u23F0 Gol de cierre{marca_prioridad}"
        return None, None
    if minuto_int >= MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
        return None, None
    if diferencia == 0:
        if presion_fav < PRESION_MIN_VICTORIA:  # C1
            return None, None
        return "posible_victoria_favorito", f"\U0001F7E2 Gana Fav{marca_prioridad}"
    if diferencia == -1:
        # C2 (B14): texto propio, solo favorito_directo y hasta el 60'.
        if DESCUENTO_SOLO_FAVORITO_DIRECTO and tipo_pronostico != "favorito_directo":
            return None, None
        if minuto_int > DESCUENTO_MAX_MINUTO:
            return None, None
        return "posible_descuento", f"\U0001F7E0 Posible descuento{marca_prioridad}"
    if diferencia > 0 and z >= 2:
        if presion_fav < PRESION_MIN_AMPLIACION:  # C3
            return None, None
        return "ampliacion_marcador", f"\U0001F535 Proximo gol: Fav{marca_prioridad}"
    return None, None


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

        # Chequeo BLANDO: favorito con ventaja minima + minimo1 remate al arco
        lado_favorito = "local" if partido["favorito_es_local"] else "visitante"
        lado_rival = "visitante" if partido["favorito_es_local"] else "local"
        presion_fav = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito)
        presion_riv = momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival)
        if presion_fav <= presion_riv:
            return None
        
        # Calcular z-score minimo
        n_fav_ev, sq_fav_ev = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_favorito)
        n_riv_ev, sq_riv_ev = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_rival)
        z_local, dominancia_fav = momentum.z_score_dominancia(
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito),
            momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival),
            n_fav_ev, n_riv_ev, sq_fav_ev, sq_riv_ev,
        )
        if abs(z_local) < 0.7:
            return None
        
        # Minimo remates al arco segun checkpoint
        stats_fav = snap_actual["stats_local"] if lado_favorito == "local" else snap_actual["stats_visitante"]
        tiros_arco = _to_float(stats_fav.get("shotsOnTarget", 0), 0)
        tiros_minimos = {22:1, 55:2, 70:3}
        if tiros_arco < tiros_minimos.get(checkpoint, 1):
            return None

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
    # C12: sin limite de una por partido; hubo_tarjeta_roja ya evita duplicados por delta.
    if ALERTA_ACTIVA.get("tarjeta_roja", True):
        if momentum.hubo_tarjeta_roja(snap_actual, snap_anterior, lado_rival):
            equipo = partido['visitante'] if lado_rival == "visitante" else partido['local']
            return [("tarjeta_roja", f"\U0001F7E5 Tarjeta roja para {equipo}.")]
        if momentum.hubo_tarjeta_roja(snap_actual, snap_anterior, lado_favorito):
            equipo = partido['local'] if lado_favorito == "local" else partido['visitante']
            return [("tarjeta_roja", f"\U0001F7E5 Tarjeta roja para {equipo}.")]

    minuto_int = momentum._minuto_a_entero(minuto) or 45
    if minuto_int < MINUTO_MINIMO_ALERTA_MOMENTUM:
        return []

    # --- Alerta de primer tiempo: ventana y umbral propios, mas suave ---
    # C5: solo favorito_directo
    if ALERTA_ACTIVA.get("alerta_1er_tiempo", True):
        if gl == 0 and gv == 0 and MINUTO_INICIO_1ER_TIEMPO <= minuto_int <= MINUTO_FIN_1ER_TIEMPO:
            if not PRIMER_TIEMPO_SOLO_FAVORITO_DIRECTO or partido.get("tipo_pronostico") == "favorito_directo":
                score_1t = _evaluar_dominancia_1er_tiempo(partido, minuto_int)
                if score_1t is not None and not _ya_se_envio_reciente(partido, "alerta_1er_tiempo", minuto_int, ventana=999):
                    dominancia_fav_1t, z_1t = score_1t
                    return [("alerta_1er_tiempo",
                              f"\u23F1\uFE0F Alerta de primer tiempo -- el favorito domina el 0-0 ({round(dominancia_fav_1t*100)}%).")]

    # --- Dominancia general (decaimiento exponencial + z-score), favorito o rival ---
    resultado = _evaluar_dominancia_general(partido, minuto_int, diferencia)
    if resultado:
        lado_resultado, dominancia_pct, z, presion_fav, presion_riv = resultado
        prioridad = partido.get("prioridad", "ALTA")
        if lado_resultado == "favorito":
            tipo, texto = _texto_alerta_favorito(diferencia, minuto_int, dominancia_pct, z, prioridad,
                                                 presion_fav=presion_fav,
                                                 tipo_pronostico=partido.get("tipo_pronostico", "favorito_directo"))
        else:
            tipo = None
            texto = None
            if minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE and ALERTA_ACTIVA.get("cuidado_rival_presiona", True):
                # C4: exigir al menos RIVAL_TIROS_PUERTA_MIN tiros a puerta del rival
                stats_riv = snap_actual[f"stats_{lado_rival}"]
                sot_riv = _to_float(stats_riv.get("shotsOnTarget", 0), 0)
                if sot_riv >= RIVAL_TIROS_PUERTA_MIN:
                    tipo = "cuidado_rival_presiona"
                    conf = momentum.etiqueta_confianza(z)
                    marca_prioridad = f" [{prioridad}]" if prioridad != "ALTA" else ""
                    texto = f"\u26A0\uFE0F Rival domina{marca_prioridad}"
        if tipo and ALERTA_ACTIVA.get(tipo, True) and not _ya_se_envio_reciente(partido, tipo, minuto_int):
            return [(tipo, texto)]

    # --- IDV: Alerta de VALUE en partidos con cuotas parejas ---
    historial = partido.get("historial_snapshots", [])
    prioridad = partido.get("prioridad", "ALTA")
    if ALERTA_ACTIVA.get("value_alert", True):
        if minuto_int >= MINUTOS_MINIMOS_IDV and minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
            datos_idv = _calcular_idv(partido, snap_actual, historial, minuto_int)
            if datos_idv and not _ya_se_envio_reciente(partido, "value_alert", minuto_int, ventana=30):
                tipo_idv, texto_idv = _mensaje_idv(datos_idv, prioridad)
                if tipo_idv:
                    return [(tipo_idv, texto_idv)]

    # --- Favorito domina pero no gana (valor en cuotas en vivo) ---
    if ALERTA_ACTIVA.get("fav_domina_no_gana", True):
        if minuto_int >= MINUTOS_MINIMOS_VALOR and minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
            resultado_fav = _evaluar_fav_domina_no_gana(partido, snap_actual, historial, minuto_int)
            if resultado_fav and not _ya_se_envio_reciente(partido, resultado_fav[0], minuto_int, ventana=30):
                return [resultado_fav]

    # --- No-favorito domina (mercado se equivoco) ---
    if ALERTA_ACTIVA.get("no_fav_domina", True):
        if minuto_int >= MINUTOS_MINIMOS_VALOR and minuto_int < MAXIMO_MINUTO_ALERTAS_NO_CIERRE:
            resultado_no_fav = _evaluar_no_favorito_domina(partido, snap_actual, historial, minuto_int)
            if resultado_no_fav and not _ya_se_envio_reciente(partido, resultado_no_fav[0], minuto_int, ventana=30):
                return [resultado_no_fav]

    # --- Chequeo "siguen empatados" (red de seguridad por tiempo) ---
    if ALERTA_ACTIVA.get("siguen_empatados", True):
        resultado_chequeo = _evaluar_chequeo_empate(partido, minuto_int, snap_actual, historial)
        if resultado_chequeo:
            return [resultado_chequeo]

    # --- Cambio de Momentum ---
    # B10: recortar historial a snapshots con minuto <= minuto_actual - 5
    if ALERTA_ACTIVA.get("cambio_momentum", True):
        if minuto_int >= 15 and len(historial) >= 3:
            historial_recortado = [s for s in historial if (momentum._minuto_a_entero(s.get("minuto")) or 0) <= minuto_int - 5]
            if len(historial_recortado) >= 1:
                n_fav_cm, sq_fav_cm = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_favorito)
                n_riv_cm, sq_riv_cm = momentum.eventos_ponderados_por_tiempo(historial, minuto_int, lado_rival)
                z_actual = momentum.z_score_dominancia(
                    momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_favorito),
                    momentum.presion_ponderada_por_tiempo(historial, minuto_int, lado_rival),
                    n_fav_cm, n_riv_cm, sq_fav_cm, sq_riv_cm,
                )[0]
                n_fav_cm2, sq_fav_cm2 = momentum.eventos_ponderados_por_tiempo(historial_recortado, minuto_int - 5, lado_favorito)
                n_riv_cm2, sq_riv_cm2 = momentum.eventos_ponderados_por_tiempo(historial_recortado, minuto_int - 5, lado_rival)
                z_anterior = momentum.z_score_dominancia(
                    momentum.presion_ponderada_por_tiempo(historial_recortado, minuto_int - 5, lado_favorito),
                    momentum.presion_ponderada_por_tiempo(historial_recortado, minuto_int - 5, lado_rival),
                    n_fav_cm2, n_riv_cm2, sq_fav_cm2, sq_riv_cm2,
                )[0]
                cambio = abs(z_actual - z_anterior)
                if cambio >= 1.5 and not _ya_se_envio_reciente(partido, "cambio_momentum", minuto_int, ventana=10):
                    direccion = "fav" if z_actual > z_anterior else "rival"
                    return [("cambio_momentum", f"\U0001F504 Cambio de momentum: {escapar_html(partido['favorito'])} {'recupera' if direccion == 'fav' else 'pierde'} control")]

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
    if z is not None:
        if z >=0:
            z_local = f"⬅️ {z:.1f}"
            z_visitante = f"{-z:.1f}"
        else:
            z_local = f"{z:.1f}"
            z_visitante = f"➡️ {-z:.1f}"
        tabla += _fila("z-score", z_local, z_visitante) + "\n"
    tabla += "</pre>"

    lineas = [f"<b>{texto}</b>"]
    lineas.append(f"{escapar_html(partido['local'])}{corona_local} <b>{gl} - {gv}</b> {escapar_html(partido['visitante'])}{corona_visitante}")
    if cuota_str:
        lineas.append(f"Cuotas: {cuota_str} | Min {minuto}")
    lineas.append(tabla)

    if dominancia_fav is not None and z is not None:
        conf = momentum.etiqueta_confianza(z)
        lado_domina = partido['favorito'] if z >=0 else partido['no_favorito']
        dominancia_mostrada = dominancia_fav if z >=0 else (1 - dominancia_fav)
        lineas.append(f"⚡ {conf} ({round(dominancia_mostrada*100)}% {escapar_html(lado_domina)})")

    historial_momentum = partido.get("historial_snapshots", [])
    if len(historial_momentum) >=2:
        momentum_local = _calcular_momentum_equipo("local", historial_momentum, True)
        momentum_visitante = _calcular_momentum_equipo("visitante", historial_momentum, False)
    
    # Poder de Match
    home_id = partido.get('home_id')
    away_id = partido.get('away_id')
    liga_slug = partido.get('liga_slug')
    if home_id and away_id and liga_slug:
        historial_local = obtener_historial_equipo(home_id, liga_slug)
        historial_visitante = obtener_historial_equipo(away_id, liga_slug)
        poder_local, color_local, n_local = _calcular_nivel_actual(historial_local, True)
        poder_visitante, color_visitante, n_visitante = _calcular_nivel_actual(historial_visitante, False)
        lineas.append(f"\U0001F4C8 Nivel Actual:")
        if poder_local is not None or poder_visitante is not None:
            if poder_local is not None:
                marca_n = f" ({n_local})" if n_local < 5 else ""
                ventana = historial_local[-6:] if len(historial_local) >= 6 else historial_local
                gf_local = sum(p['goles_favor'] for p in ventana)
                gc_local = sum(p['goles_contra'] for p in ventana)
                lineas.append(f"{color_local} {escapar_html(partido['local'])}: {poder_local:.1f}{marca_n} (GF:{gf_local} GC:{gc_local})")
            if poder_visitante is not None:
                marca_n = f" ({n_visitante})" if n_visitante < 5 else ""
                ventana = historial_visitante[-6:] if len(historial_visitante) >= 6 else historial_visitante
                gf_visitante = sum(p['goles_favor'] for p in ventana)
                gc_visitante = sum(p['goles_contra'] for p in ventana)
                lineas.append(f"{color_visitante} {escapar_html(partido['visitante'])}: {poder_visitante:.1f}{marca_n} (GF:{gf_visitante} GC:{gc_visitante})")
        else:
            lineas.append("No hay datos suficientes")

    if "value" in texto.lower() or "VALUE" in texto:
        historial = partido.get("historial_snapshots", [])
        datos_idv = _calcular_idv(partido, snap_actual, historial, momentum._minuto_a_entero(minuto) or 0)
        if datos_idv:
            lineas.append(f"\U0001F4CA IDV: {round(datos_idv['idv'],1)} | OD:{round(datos_idv['od'],3)} MS:{round(datos_idv['ms'],3)} SD:{round(datos_idv['sd'],3)} TC:{round(datos_idv['tc'],3)} CF:{round(datos_idv['cf'],3)}")
            lineas.append(f"\U0001F4B0 Cuota fav: {datos_idv['cuota_fav']} | Posesion: {round(datos_idv['posesion_fav'])}% | Tiros: {datos_idv['tiros_fav']}-{datos_idv['tiros_riv']} | z={datos_idv['z']:.1f}")

    fecha_partido = partido.get('hora_inicio', '')[:10] if partido.get('hora_inicio') else ''
    fecha_exacta = fecha_partido if fecha_partido else ''
    
    local_search = partido['local'].replace(' ', '+')
    visitante_search = partido['visitante'].replace(' ', '+')
    
    keyboard = [[
        {"text": "⚽ BeSoccer", "url": f"https://www.google.com/search?q=site:besoccer.com+{local_search}+vs+{visitante_search}+{fecha_exacta}"},
        {"text": "📊 SofaScore", "url": f"https://www.google.com/search?q=site:sofascore.com+{local_search}+vs+{visitante_search}+{fecha_exacta}"},
    ],[
        {"text": "⚡ Flashscore", "url": f"https://www.google.com/search?q=site:flashscore.com+{local_search}+vs+{visitante_search}+{fecha_exacta}"},
        {"text": "🎰 1xBet", "url": f"https://www.google.com/search?q=site:1xbet.com+{local_search}+vs+{visitante_search}+{fecha_exacta}"},
    ]]
    reply_markup = {"inline_keyboard": keyboard}

    return "\n".join(lineas), reply_markup


def _enviar_resoluciones(partido, datos, resueltas, gl, gv):
    """Manda un mensaje por alerta resuelta (R3) y marca
    resolucion_notificada SOLO si Telegram acepto el mensaje -- si
    falla, queda pendiente y se reintenta en el proximo ciclo."""
    cambios = False
    for alerta in resueltas:
        linea = linea_efectividad(datos.get("partidos", []), alerta.get("tipo"))
        texto = mensaje_resolucion(alerta, partido, f"{gl}-{gv}", linea)
        if enviar_mensaje_telegram(texto):
            alerta["resolucion_notificada"] = True
            cambios = True
    return cambios


def _mensaje_partido_finalizado(partido, gh, gv, resueltas=None):
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
    if RESOLUCION_MODO == "resumen_final" and resueltas:
        # En modo resumen no hubo mensajes sueltos: se listan aqui.
        from resolucion_alertas import ETIQUETA_TIPO
        lineas.append("")
        for alerta in resueltas:
            etiqueta = ETIQUETA_TIPO.get(alerta.get("tipo"), alerta.get("tipo", ""))
            marca_a = {"acierto": "\u2705", "fallo": "\u274C"}.get(alerta.get("estado"), "\u2796")
            lineas.append(f"{marca_a} {etiqueta} (min {alerta.get('minuto', '?')}')")
    return "\n".join(lineas)


def vigilar():
    # SIN alarma global: con 100+ partidos un ciclo puede tardar varios
    # minutos y una alarma fija cortaba a la mitad perdiendo TODO el
    # progreso (el guardado estaba solo al final). Los requests ya tienen
    # timeout propio y cada partido va en try/except + guardado
    # incremental dentro de _vigilar_interno.
    try:
        _vigilar_interno()
    except Exception:
        print("[ERROR] Excepcion no capturada en vigilar():")
        traceback.print_exc()
    try:
        Path(DATA_DIR, ".fase3_heartbeat").write_text(datetime.datetime.now(datetime.timezone.utc).isoformat(), encoding="utf-8")
    except Exception as e:
        print(f"[AVISO] No se pudo escribir heartbeat: {e}")


def _vigilar_interno():
    global PREDICCIONES_ACTIVAS, HISTORIAL_PREDICCIONES
    datos = _cargar()
    if not datos or "partidos" not in datos:
        print("No hay partidos_hoy.json todavia. Se reintentara en el proximo ciclo.")
        return

    PREDICCIONES_ACTIVAS = datos.get("predicciones_activas", {})
    HISTORIAL_PREDICCIONES = datos.get("historial_predicciones", {})

    hubo_cambios = False
    procesados = 0
    for partido in datos["partidos"]:
        try:
            procesados += 1
            # R5.4: si ya se mando el finalizado, solo se sigue consultando
            # cuando queden alertas pendientes o resoluciones sin notificar.
            # (Antes se saltaba siempre y nada se resolvia despues.)
            if not partido.get("fixture_id"):
                continue
            if partido.get("aviso_final_enviado") and not tiene_trabajo_pendiente(partido):
                continue
            if not _en_ventana_horaria(partido):
                continue

            liga_slug = partido.get("liga_slug")
            if not liga_slug or liga_slug == "all":
                # F1: el slug "all" NO sirve para el summary en vivo,
                # pero el scoreboard global SI funciona. Se usa para
                # detectar si el partido termino y enviar el aviso final
                # con resolucion de alertas pendientes.
                if not partido.get("aviso_final_enviado"):
                    estado = obtener_estado_desde_scoreboard(
                        partido["fixture_id"], datos.get("fecha", ""))
                    if estado and estado.get("estado") == "post":
                        gl = estado.get("goles_local")
                        gv = estado.get("goles_visitante")
                        if gl is not None and gv is not None:
                            snap_fin = {"minuto": estado.get("minuto"),
                                        "goles_local": gl, "goles_visitante": gv,
                                        "stats_local": {}, "stats_visitante": {}}
                            resueltas = resolver_pendientes(
                                partido, None, snap_fin, terminado=True,
                                marcador_final=(gl, gv),
                                sin_gol_es_fallo=SIN_GOL_ES_FALLO)
                            if resueltas and RESOLUCION_MODO == "individual":
                                if _enviar_resoluciones(partido, datos, resueltas, gl, gv):
                                    hubo_cambios = True
                            mensaje = _mensaje_partido_finalizado(partido, gl, gv, resueltas)
                            if enviar_mensaje_telegram(mensaje):
                                partido["aviso_final_enviado"] = True
                                hubo_cambios = True
                                PREDICCIONES_ACTIVAS.pop(partido.get("fixture_id"), None)
                    elif estado and estado.get("estado") == "in":
                        pass  # en vivo pero sin stats: no se monitorea
                    else:
                        pass  # pre o None: todavia no empieza / sin datos
                continue

            box = obtener_boxscore_en_vivo(liga_slug, partido["fixture_id"])
            if box is None:
                continue

            if box.get("estado") == "post":
                # R5.2: primero se resuelve lo pendiente contra el marcador
                # final (B2: antes se borraba en silencio), se notifica y
                # DESPUES va el "finalizado". Solo entonces se marca.
                gl, gv = box["goles_local"], box["goles_visitante"]
                historial_fin = partido.get("historial_snapshots", [])
                snap_ult = historial_fin[-1] if historial_fin else None
                snap_fin = {"minuto": box.get("minuto"), "goles_local": gl,
                            "goles_visitante": gv, "stats_local": {},
                            "stats_visitante": {}}
                resueltas = resolver_pendientes(
                    partido, snap_ult, snap_fin, terminado=True,
                    marcador_final=(gl, gv), sin_gol_es_fallo=SIN_GOL_ES_FALLO)
                if resueltas and RESOLUCION_MODO == "individual":
                    if _enviar_resoluciones(partido, datos, resueltas, gl, gv):
                        hubo_cambios = True
                mensaje = _mensaje_partido_finalizado(partido, gl, gv, resueltas)
                if enviar_mensaje_telegram(mensaje):
                    partido["aviso_final_enviado"] = True
                    hubo_cambios = True
                    PREDICCIONES_ACTIVAS.pop(partido.get("fixture_id"), None)
                continue

            if box.get("estado") != "in":
                continue

            snap_actual = {
                "minuto": box["minuto"], "goles_local": box["goles_local"],
                "goles_visitante": box["goles_visitante"],
                "stats_local": dict(box["stats_local"]), "stats_visitante": dict(box["stats_visitante"]),
                "periodo": box.get("periodo"),               # R4 (fin_1t)
                "estado_detalle": box.get("estado_detalle"),  # R4 (fin_1t)
            }
            historial = partido.setdefault("historial_snapshots", [])
            snap_anterior = historial[-1] if historial else None
            historial.append(snap_actual)
            hubo_cambios = True

            # R5.3: resolver pendientes ANTES de evaluar alertas nuevas --
            # una alerta de este ciclo nunca se resuelve con un gol anterior.
            # (Reemplaza al sistema viejo de PREDICCIONES_ACTIVAS, B1-B4.)
            resueltas = resolver_pendientes(
                partido, snap_anterior, snap_actual,
                sin_gol_es_fallo=SIN_GOL_ES_FALLO)
            if resueltas and RESOLUCION_MODO == "individual":
                _enviar_resoluciones(partido, datos, resueltas,
                                     box["goles_local"], box["goles_visitante"])

            favorito_es_local = partido["favorito_es_local"]
            goles_favorito = box["goles_local"] if favorito_es_local else box["goles_visitante"]
            goles_rival = box["goles_visitante"] if favorito_es_local else box["goles_local"]
            diferencia_actual = goles_favorito - goles_rival

            lado_favorito = "local" if favorito_es_local else "visitante"
            lado_rival = "visitante" if favorito_es_local else "local"

            z = 0.0
            dominancia_fav = 0.5
            minuto_int = momentum._minuto_a_entero(box["minuto"]) or 0

            if minuto_int >= 5 and len(historial) >= 2:
                presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv = _presiones_y_eventos(historial, minuto_int, lado_favorito, lado_rival)
                z, dominancia_fav = momentum.z_score_dominancia(presion_fav, presion_riv, n_fav, n_riv, sq_fav, sq_riv)

            alertas = _evaluar_alertas(partido, snap_actual, snap_anterior, box["minuto"])

            for tipo, texto in alertas:
                mensaje, reply_markup = _mensaje_partido(partido, box["minuto"], snap_actual, texto,
                                            dominancia_fav=dominancia_fav, z=z)
                if enviar_mensaje_telegram(mensaje, reply_markup=reply_markup):
                    _registrar_alerta(partido, tipo, texto, box["minuto"], diferencia_goles=diferencia_actual,
                                      marcador=[box["goles_local"], box["goles_visitante"]])

            # Guardado incremental: si el ciclo muere a la mitad (runner
            # caido, timeout del job), lo ya procesado no se pierde.
            if hubo_cambios and procesados % 15 == 0:
                try:
                    _guardar(datos)
                except Exception as e:
                    print(f"[AVISO] Guardado incremental fallo: {e}")
        except Exception as e:
            try:
                fid_err = partido.get("fixture_id", "?")
            except Exception:
                fid_err = "?"
            print(f"[AVISO] Fallo procesando partido {fid_err}, se sigue con el siguiente: {e}")

    if hubo_cambios:
        _guardar(datos)


if __name__ == "__main__":
    vigilar()

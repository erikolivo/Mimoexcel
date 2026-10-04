"""Favoritos diarios desde el dashboard elo-tilt (solo lectura).

Mismo esquema que google_favoritos.interpretar_csv, pero la fuente es
el JSON publico que el repo erikolivo/elo-tilt sube a GitHub
(data/predicciones_cache.json y data/predicciones_YYYY-MM-DD.json).
elo-tilt NO se modifica: aqui solo se descarga y se interpreta su JSON.

Cada prediccion de elo-tilt trae las probabilidades 1X2 del modelo y
el fixture_id de ESPN, asi que la union con los fixtures del dia es
directa (por id, sin fuzzy match).

Regla de favorito (calibrada al estilo de la hoja de Google Sheets):
  - lado con mayor probabilidad >= 60%  -> LOCAL / VISITANTE (directo)
  - 45% <= lado < 60%                   -> DC LOCAL / DC VISITANTE
  - < 45%                               -> se descarta (sin favorito claro)

La prioridad sale de 'confianza' (|diff_elo|/200*100 de elo-tilt):
ALTA si >= 60, MEDIA si >= 35, BAJA si no. monitor.py sube el umbral
z con prioridades bajas, asi los cientos de partidos diarios del modelo
generan menos ruido.
"""

import datetime

import requests

FUENTE = "elo-tilt"
_BASE = "https://raw.githubusercontent.com/erikolivo/elo-tilt/master/data"
URL_CACHE = f"{_BASE}/predicciones_cache.json"
URL_POR_FECHA = _BASE + "/predicciones_{fecha}.json"
TIMEOUT = 30
UMBRAL_DIRECTO = 60.0
UMBRAL_DC = 45.0


def _favorito_desde_probs(prediccion):
    """LOCAL/VISITANTE si el lado mas probable supera UMBRAL_DIRECTO,
    DC <lado> si esta en la banda intermedia, None si no hay favorito
    claro."""
    prob_local = float(prediccion.get("prob_local") or 0)
    prob_visitante = float(prediccion.get("prob_visitante") or 0)
    lado, prob = ("LOCAL", prob_local) if prob_local >= prob_visitante else ("VISITANTE", prob_visitante)
    if prob >= UMBRAL_DIRECTO:
        return lado
    if prob >= UMBRAL_DC:
        return f"DC {lado}"
    return None


def _prioridad_desde_confianza(confianza):
    if confianza >= 60:
        return "ALTA", 3
    if confianza >= 35:
        return "MEDIA", 2
    return "BAJA", 1


def interpretar_predicciones(datos, hoy):
    """Convierte el JSON de elo-tilt en entradas con la misma forma que
    google_favoritos.interpretar_csv. Devuelve [] si los datos no son
    de 'hoy' (un cache viejo no sirve para la seleccion del dia)."""
    if (datos.get("fecha_consulta") or "") != hoy.isoformat():
        return []
    entradas = []
    for pred in datos.get("predicciones", []):
        favorito = _favorito_desde_probs(pred.get("prediccion", {}))
        if not favorito:
            continue
        confianza = float(pred.get("confianza") or 0)
        prioridad, estrellas = _prioridad_desde_confianza(confianza)
        entradas.append({
            "local": str(pred.get("equipo_local", {}).get("nombre", "")).strip(),
            "visitante": str(pred.get("equipo_visitante", {}).get("nombre", "")).strip(),
            "favorito": favorito,
            "fila_hoja": str(pred.get("fixture_id") or ""),
            "confianza_texto": "*" * estrellas,
            "confianza_estrellas": estrellas,
            "cuota_local": None, "cuota_empate": None, "cuota_visitante": None,
            "prioridad": prioridad,
            "fixture_id": str(pred.get("fixture_id") or ""),
        })
    return entradas


def _descargar(url):
    respuesta = requests.get(url, timeout=TIMEOUT)
    if respuesta.status_code != 200:
        return None
    return respuesta.json()


def obtener_favoritos_elo_tilt(hoy=None):
    """Descarga los favoritos de elo-tilt para la fecha dada (hoy por
    defecto). Prima primero el archivo del dia (predicciones_YYYY-MM-DD
    .json, que elo-tilt escribe en cada corrida) y despues su cache,
    siempre que este marcado con la fecha de hoy. Sin datos frescos
    devuelve [] -- seleccionar_partidos.py decide que hacer."""
    hoy = hoy or datetime.date.today()
    urls = [URL_POR_FECHA.format(fecha=hoy.isoformat()), URL_CACHE]
    for url in urls:
        try:
            datos = _descargar(url)
        except (requests.RequestException, ValueError) as error:
            print(f"[AVISO] elo-tilt no respondio ({url}): {error}")
            continue
        if datos is None:
            continue
        entradas = interpretar_predicciones(datos, hoy)
        if entradas:
            return entradas
    return []

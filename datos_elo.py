"""Elo, forma y overperformance de cada equipo, desde elo-tilt (solo lectura).

elo-tilt publica en data/predicciones_YYYY-MM-DD.json (y en su cache) una
ficha por equipo con rating Elo, forma reciente y overperformance. Este
modulo la busca para el partido de la alerta (primero por fixture_id de
ESPN y, si no aparece, por nombres) y arma las lineas del mensaje.

Si elo-tilt no responde o el partido no esta en su cobertura, se completa
al menos el Elo con ratings_propios.json (via historial_elo.rating_de) y,
si tampoco hay, no se agrega nada al mensaje. Nada de esto lanza.
"""

import datetime
import unicodedata

import requests

import historial_elo
from telegram_utils import escapar_html

BASE = "https://raw.githubusercontent.com/erikolivo/elo-tilt/master/data"
URL_CACHE = f"{BASE}/predicciones_cache.json"
URL_POR_FECHA = BASE + "/predicciones_{fecha}.json"
TIMEOUT = 30
TTL_SEGUNDOS = 1800         # 30 min: el monitor corre cada pocos minutos

_cache = {"fecha": None, "cargado": None, "por_fixture": {}, "por_nombres": {}}


def _clave(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return " ".join(texto.split())


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _vigente():
    cargado = _cache.get("cargado")
    if not cargado:
        return False
    return (datetime.datetime.now() - cargado).total_seconds() < TTL_SEGUNDOS


def _indexar(predicciones):
    por_fixture, por_nombres = {}, {}
    for pred in predicciones or []:
        if not isinstance(pred, dict):
            continue
        fixture = pred.get("fixture_id")
        if fixture not in (None, ""):
            por_fixture[str(fixture)] = pred
        local = str((pred.get("equipo_local") or {}).get("nombre") or "").strip()
        visitante = str((pred.get("equipo_visitante") or {}).get("nombre") or "").strip()
        if local and visitante:
            por_nombres[(_clave(local), _clave(visitante))] = pred
    return por_fixture, por_nombres


def obtener_datos(hoy=None, forzar=False):
    """Devuelve (por_fixture, por_nombres) de las predicciones de hoy.

    Prueba primero el archivo del dia y despues el cache, igual que
    elo_tilt_favoritos. Solo acepta datos con fecha_consulta == hoy: un
    cache viejo mostraria Elo y forma de otro dia. Ante cualquier fallo
    devuelve lo ultimo valido de hoy (o vacio) sin lanzar.
    """
    hoy = hoy or datetime.date.today()
    fecha = hoy.isoformat()
    if not forzar and _cache["fecha"] == fecha and _vigente():
        return _cache["por_fixture"], _cache["por_nombres"]

    for url in (URL_POR_FECHA.format(fecha=fecha), URL_CACHE):
        try:
            respuesta = requests.get(url, timeout=TIMEOUT)
            if respuesta.status_code != 200:
                continue
            datos = respuesta.json()
        except (requests.RequestException, ValueError):
            continue
        if not isinstance(datos, dict) or str(datos.get("fecha_consulta") or "") != fecha:
            continue
        por_fixture, por_nombres = _indexar(datos.get("predicciones"))
        if por_fixture:
            _cache.update({"fecha": fecha, "cargado": datetime.datetime.now(),
                           "por_fixture": por_fixture, "por_nombres": por_nombres})
            return por_fixture, por_nombres

    if _cache["fecha"] == fecha:
        return _cache["por_fixture"], _cache["por_nombres"]
    return {}, {}


def _resumen_equipo(equipo):
    """Solo los campos que se muestran en la alerta, o None."""
    if not isinstance(equipo, dict):
        return None
    ultimos = equipo.get("ultimos5") if isinstance(equipo.get("ultimos5"), dict) else {}
    resumen = {
        "nombre": str(equipo.get("nombre") or "").strip(),
        "rating": _numero(equipo.get("rating")),
        "form_score": _numero(equipo.get("form_score")),
        "forma": str(ultimos.get("texto") or "").strip() or None,
        "overperformance": _numero(equipo.get("overperformance")),
        "momentum": equipo.get("momentum"),
    }
    return resumen if any(valor is not None for clave, valor in resumen.items() if clave != "nombre") else None


def datos_de_partido(partido):
    """Ficha local/visitante para un partido, o None si no hay nada.

    Primero busca por fixture_id (union directa con ESPN); si elo-tilt no
    cubre ese id, por la pareja de nombres. Si falta el rating, lo
    completa con ratings_propios.json (historial_elo.rating_de).
    """
    try:
        por_fixture, por_nombres = obtener_datos()
        pred = por_fixture.get(str(partido.get("fixture_id"))) if partido.get("fixture_id") not in (None, "") else None
        if pred is None:
            clave = (_clave(partido.get("local")), _clave(partido.get("visitante")))
            pred = por_nombres.get(clave)

        datos = {"local": None, "visitante": None}
        if pred:
            datos["local"] = _resumen_equipo(pred.get("equipo_local"))
            datos["visitante"] = _resumen_equipo(pred.get("equipo_visitante"))

        for lado, team_id in (("local", partido.get("home_id")), ("visitante", partido.get("away_id"))):
            if (datos.get(lado) or {}).get("rating") is not None:
                continue
            rating = historial_elo.rating_de(team_id)
            if rating:
                datos[lado] = datos[lado] or {
                    "nombre": "", "form_score": None, "forma": None,
                    "overperformance": None, "momentum": None,
                }
                datos[lado]["rating"] = rating.get("rating")

        return datos if (datos["local"] or datos["visitante"]) else None
    except Exception:
        return None


def _texto_equipo(nombre, datos):
    partes = []
    if datos.get("rating") is not None:
        partes.append(f"Elo {datos['rating']:.0f}")
    if datos.get("forma"):
        forma = f"forma {datos['forma']}"
        if datos.get("form_score") is not None:
            forma += f" · {datos['form_score']:.0f}"
        partes.append(forma)
    if datos.get("overperformance") is not None:
        partes.append(f"overperf {datos['overperformance']:+.1f}")
    if not partes:
        return None
    return f"  {escapar_html(nombre)}: " + " | ".join(partes)


def lineas_elo(partido):
    """Lineas listas para el mensaje de Telegram (vacio si no hay datos)."""
    try:
        datos = datos_de_partido(partido)
        if not datos:
            return []
        lineas = ["📐 Elo y forma (elo-tilt):"]
        agregadas = 0
        for lado, etiqueta in (("local", partido.get("local")), ("visitante", partido.get("visitante"))):
            ficha = datos.get(lado)
            if not ficha:
                continue
            # Se usa el nombre que ya trae el partido (mismo que el resto
            # del mensaje); el de elo-tilt a veces viene abreviado.
            nombre = str(etiqueta or ficha.get("nombre") or lado)
            linea = _texto_equipo(nombre, ficha)
            if linea:
                lineas.append(linea)
                agregadas += 1
        return lineas if agregadas else []
    except Exception:
        return []

"""Historial de partidos desde los datos publicos de elo-tilt (solo lectura).

elo-tilt (github.com/erikolivo/elo-tilt) publica
``data/historial_partidos/{YYYY-MM}.json`` con los partidos ya jugados de
todas las competiciones. Se usa como fuente PRINCIPAL del historial de un
equipo porque:

- incluye liga local y copas/competiciones internacionales en un solo
  archivo (el endpoint internacional de ESPN devolvia 404);
- no depende de como numera ESPN las temporadas.

Si un equipo no tiene suficientes partidos aqui (recien ascendido, liga
que elo-tilt no cubre), fetch_data cae al historial de ESPN.

Nada de este modulo escribe en el repositorio de elo-tilt: solo se leen
archivos por HTTPS. Las funciones publicas nunca lanzan excepciones.
"""

import json
import os
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

BASE_ELO = "https://raw.githubusercontent.com/erikolivo/elo-tilt/master/data"
URL_HISTORIAL = BASE_ELO + "/historial_partidos/{mes}.json"
URL_RATINGS = BASE_ELO + "/ratings_propios.json"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_FILE = os.path.join(DATA_DIR, "cache_historial_elo.json")
# Respaldo local si elo-tilt no responde (mismo formato: {"equipos": {...}}).
RATINGS_LOCAL_FILE = os.path.join(DATA_DIR, "ratings_propios.json")

MESES_MAXIMOS = 3          # ventana hacia atras (mes actual incluido)
MIN_PARTIDOS = 8           # con esto ya no se siguen leyendo meses
MAX_PARTIDOS = 30          # tope del historial devuelto
CACHE_HORAS = 3
TIMEOUT = 20
REINTENTOS = 2

USER_AGENT = "alertas-favoritos/1.0 (historial elo-tilt)"

_cache_memoria = {}
# El archivo mensual de elo-tilt pesa ~3 MB: se cachea UNA vez por proceso
# y mes (si no, cada equipo lo volveria a descargar).
_cache_meses = {}
_cache_ratings = {"cargado_en": None, "equipos": {}}


def _ahora():
    """Indireccion para poder simular el paso del tiempo en tests."""
    return datetime.now()


def _sin_acentos(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def _meses_a_consultar(hoy=None):
    """['2026-10', '2026-09', '2026-08'] para 2026-10-28 (mas reciente primero)."""
    hoy = hoy or date.today()
    meses = []
    anio, mes = hoy.year, hoy.month
    for _ in range(MESES_MAXIMOS):
        meses.append(f"{anio:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes = 12
            anio -= 1
    return meses


def _es_amistoso(partido):
    etiquetas = (_sin_acentos(partido.get("liga_slug")), _sin_acentos(partido.get("liga_nombre")))
    return any("friendly" in etiqueta or "amistoso" in etiqueta for etiqueta in etiquetas)


def _partidos_del_equipo(datos, team_id):
    """Filtra el archivo mensual a los partidos jugados por team_id.

    Reglas: sin amistosos, sin marcador incompleto (None), sin duplicados
    por fixture_id y en orden cronologico ascendente."""
    partidos = datos.get("partidos", []) if isinstance(datos, dict) else (datos or [])
    team_id = str(team_id)
    vistos = set()
    historial = []
    for partido in partidos:
        if not isinstance(partido, dict) or _es_amistoso(partido):
            continue
        local = str((partido.get("equipo_local") or {}).get("id") or "")
        visitante = str((partido.get("equipo_visitante") or {}).get("id") or "")
        if team_id not in (local, visitante):
            continue
        gf = partido.get("goles_local")
        gc = partido.get("goles_visitante")
        if gf is None or gc is None:
            continue
        try:
            gf, gc = int(gf), int(gc)
        except (TypeError, ValueError):
            continue
        fecha = str(partido.get("fecha") or partido.get("fecha_hora_espn") or "")[:10]
        if not fecha:
            continue
        es_local = team_id == local
        rival_id = visitante if es_local else local
        fixture_id = str(partido.get("fixture_id") or "")
        clave = fixture_id or f"{fecha}|{rival_id}|{gf}-{gc}"
        if clave in vistos:
            continue
        vistos.add(clave)
        goles_favor = gf if es_local else gc
        goles_contra = gc if es_local else gf
        resultado = "V" if goles_favor > goles_contra else ("D" if goles_favor < goles_contra else "E")
        historial.append({
            "id": fixture_id or clave,
            "fecha": fecha,
            "goles_favor": goles_favor,
            "goles_contra": goles_contra,
            "es_local": es_local,
            "resultado": resultado,
            "rival_id": rival_id,
            "competicion": partido.get("liga_slug") or partido.get("liga_nombre") or "",
        })
    historial.sort(key=lambda p: (p["fecha"], p["id"]))
    return historial


def _descargar_json(url, etiqueta):
    """Descarga JSON de elo-tilt. Devuelve (estado, datos).

    estado: 'ok' | '404' (no publicado) | 'error' (red/JSON tras reintentos)."""
    ultimo_error = None
    for intento in range(REINTENTOS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as respuesta:
                return "ok", json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return "404", None
            ultimo_error = error
        except Exception as error:   # red, timeout, JSON invalido
            ultimo_error = error
        if intento < REINTENTOS:
            time.sleep(1 + intento)
    print(f"[AVISO] elo-tilt {etiqueta}: {ultimo_error}")
    return "error", None


def _descargar_mes(mes):
    """Descarga un archivo mensual (una sola vez por proceso).

    [] si no existe (404); None si fallo la red."""
    en_memoria = _cache_meses.get(mes)
    if en_memoria and _vigente(en_memoria[0]):
        return en_memoria[1]
    estado, datos = _descargar_json(URL_HISTORIAL.format(mes=mes), f"historial {mes}")
    if estado == "ok":
        resultado = datos
    else:
        resultado = [] if estado == "404" else None
    if resultado is not None:
        _cache_meses[mes] = (_ahora().isoformat(), resultado)
    return resultado


def _leer_cache_disco():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as archivo:
            cache = json.load(archivo)
        return cache if isinstance(cache, dict) else {}
    except Exception:
        return {}


def _guardar_cache_disco(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as archivo:
            json.dump(cache, archivo, ensure_ascii=False, indent=2)
    except Exception as error:
        print(f"[AVISO] no se pudo guardar el cache de historial elo-tilt: {error}")


def _vigente(fecha_cache):
    try:
        return _ahora() - datetime.fromisoformat(fecha_cache) < timedelta(hours=CACHE_HORAS)
    except Exception:
        return False


def _leer_ratings_locales():
    try:
        with open(RATINGS_LOCAL_FILE, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except Exception:
        return None


def _cargar_ratings():
    """{'espn:<id>': {rating, rd, ...}} desde elo-tilt o el respaldo local.

    Cache en memoria de 3 h. Si no hay datos devuelve {} y no cachea el
    fallo, para reintentar en la proxima llamada."""
    equipos = _cache_ratings["equipos"]
    if equipos and _vigente(_cache_ratings["cargado_en"]):
        return equipos

    estado, datos = _descargar_json(URL_RATINGS, "ratings_propios")
    if estado != "ok" or not isinstance(datos, dict):
        datos = _leer_ratings_locales()
    if isinstance(datos, dict):
        crudos = datos.get("equipos") if isinstance(datos.get("equipos"), dict) else datos
        equipos = {clave: valor for clave, valor in crudos.items() if isinstance(valor, dict)}
    else:
        equipos = {}

    if equipos:
        _cache_ratings["equipos"] = equipos
        _cache_ratings["cargado_en"] = _ahora().isoformat()
    return equipos


def rating_de(team_id):
    """Rating propio del equipo segun elo-tilt, o None.

    Devuelve {'rating': float, 'rd': float|None}. Fuente principal:
    data/ratings_propios.json de elo-tilt; respaldo local:
    data/ratings_propios.json del repo. Nunca lanza excepciones."""
    try:
        if team_id in (None, ""):
            return None
        equipos = _cargar_ratings()
        clave = str(team_id)
        entrada = equipos.get(f"espn:{clave}") or equipos.get(clave)
        if not isinstance(entrada, dict):
            return None
        valor = float(entrada.get("rating"))
        rd = entrada.get("rd")
        return {"rating": valor, "rd": float(rd) if rd is not None else None}
    except Exception:
        return None


def _historial_mes(team_id, mes, cache_disco, ahora_iso):
    """Historial de un equipo en un mes, con cache en memoria y en disco."""
    clave = f"{team_id}|{mes}"
    en_memoria = _cache_memoria.get(clave)
    if en_memoria and _vigente(en_memoria[0]):
        return en_memoria[1]

    en_disco = cache_disco.get(clave)
    if isinstance(en_disco, dict) and _vigente(en_disco.get("fecha_cache")):
        historial = en_disco.get("historial") or []
        _cache_memoria[clave] = (en_disco["fecha_cache"], historial)
        return historial

    datos = _descargar_mes(mes)
    if datos is None:
        return []   # fallo de red: se intenta el siguiente mes, sin cachear
    historial = _partidos_del_equipo(datos, team_id)
    _cache_memoria[clave] = (ahora_iso, historial)
    cache_disco[clave] = {"fecha_cache": ahora_iso, "historial": historial}
    return historial


def obtener_historial_equipo_elo(team_id, hoy=None):
    """Ultimos partidos del equipo segun elo-tilt (mas reciente al final).

    Lee como maximo los ultimos 3 meses y se detiene al juntar
    MIN_PARTIDOS. Devuelve [] si no hay datos suficientes o si algo falla.
    Cada elemento: {id, fecha, goles_favor, goles_contra, es_local,
    resultado, rival_id, competicion}.
    """
    if team_id in (None, ""):
        return []
    try:
        team_id = str(team_id)
        ahora = _ahora()
        ahora_iso = ahora.isoformat()
        cache_disco = _leer_cache_disco()
        vistos = set()
        historial = []
        for mes in _meses_a_consultar(hoy):
            for partido in _historial_mes(team_id, mes, cache_disco, ahora_iso):
                if partido["id"] in vistos:
                    continue
                vistos.add(partido["id"])
                historial.append(partido)
            if len(historial) >= MIN_PARTIDOS:
                break
        _guardar_cache_disco(cache_disco)
        historial.sort(key=lambda p: (p["fecha"], p["id"]))
        return historial[-MAX_PARTIDOS:]
    except Exception as error:
        print(f"[AVISO] historial elo-tilt equipo {team_id}: {error}")
        return []


if __name__ == "__main__":
    import sys

    equipo = sys.argv[1] if len(sys.argv) > 1 else "86"
    datos = obtener_historial_equipo_elo(equipo)
    print(f"equipo {equipo}: {len(datos)} partidos")
    for partido in datos[-8:]:
        print("  ", partido)

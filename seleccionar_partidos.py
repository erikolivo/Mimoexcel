"""Fase 1: prepara para vigilancia los favoritos diarios.

Fuente principal: Google Sheets (la hoja que se llena a mano). Si la
hoja falla o devuelve 0 favoritos para hoy, se usa como respaldo elo
tilt (erikolivo/elo-tilt, solo lectura -- ver elo_tilt_favoritos.py).
"""

import datetime
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

from elo_tilt_favoritos import obtener_favoritos_elo_tilt
from fetch_data import obtener_fixtures_por_fecha
from google_favoritos import normalizar, obtener_favoritos_google
from thesportsdb_aliases import nombres_alternativos

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARCHIVO_SALIDA = DATA_DIR / "partidos_hoy.json"
ARCHIVO_CACHE_ALIAS = DATA_DIR / "alias_equipos_cache.json"
ARCHIVO_PENDIENTES = DATA_DIR / "pendientes_revision.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))
VERSION_SELECCION = 6
FUENTES_VALIDAS = {"Google Sheets", "elo-tilt"}

# Alias FIJADOS A MANO -- para casos que se quieren garantizar sin
# depender de que el fuzzy match o TheSportsDB los resuelvan. La
# mayoria de los casos nuevos ya NO necesitan pasar por aqui: se
# resuelven y se recuerdan solos en ARCHIVO_CACHE_ALIAS (ver
# _registrar_alias_aprendido mas abajo).
ALIAS_EQUIPOS = {
    "wolves": "wolverhampton wanderers",
    "aarhus": "agf",
}
SUFIJOS_EQUIPO = {"fc", "cf", "fk", "ff", "sc", "afc", "ac"}

_cache_alias_memoria = None


def _cargar_cache_alias():
    global _cache_alias_memoria
    if _cache_alias_memoria is None:
        if ARCHIVO_CACHE_ALIAS.exists():
            try:
                _cache_alias_memoria = json.loads(ARCHIVO_CACHE_ALIAS.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _cache_alias_memoria = {}
        else:
            _cache_alias_memoria = {}
    return _cache_alias_memoria


def _registrar_alias_aprendido(nombre_hoja, nombre_espn):
    """Guarda nombre_de_la_hoja -> nombre_oficial_ESPN la primera vez
    que se resuelve por un camino no trivial (fuzzy o TheSportsDB), asi
    el proximo dia que aparezca ese mismo nombre en la hoja el match es
    directo -- sin gastar peticion a TheSportsDB ni depender de que el
    ratio de similitud vuelva a alcanzar el corte."""
    clave = normalizar(nombre_hoja)
    if not clave or clave == normalizar(nombre_espn):
        return  # ya coincide directo, no hace falta aprender nada
    cache = _cargar_cache_alias()
    if cache.get(clave) == nombre_espn:
        return
    cache[clave] = nombre_espn
    ARCHIVO_CACHE_ALIAS.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _registrar_pendiente(entrada, motivo, fecha):
    """Log acotado de partidos que no se lograron ubicar en ESPN, para
    revisar de vez en cuando (probablemente ligas que ESPN no cubre, o
    un alias nuevo que conviene fijar a mano en ALIAS_EQUIPOS)."""
    pendientes = []
    if ARCHIVO_PENDIENTES.exists():
        try:
            pendientes = json.loads(ARCHIVO_PENDIENTES.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pendientes = []
    pendientes.append({
        "fecha": fecha, "local": entrada["local"], "visitante": entrada["visitante"],
        "favorito": entrada.get("favorito"), "motivo": motivo,
    })
    pendientes = pendientes[-200:]
    ARCHIVO_PENDIENTES.write_text(json.dumps(pendientes, ensure_ascii=False, indent=2), encoding="utf-8")


def fecha_local_hoy():
    return datetime.datetime.now(ZONA_HORARIA_LOCAL).date().isoformat()


def ya_se_completo_hoy():
    if not ARCHIVO_SALIDA.exists():
        return False
    try:
        datos = json.loads(ARCHIVO_SALIDA.read_text(encoding="utf-8"))
        partidos = datos.get("partidos", [])
        return (
            datos.get("fecha") == fecha_local_hoy()
            and datos.get("seleccion_version") == VERSION_SELECCION
            and len(partidos) > 0  # 0 partidos casi siempre es un fallo silencioso, no un dia sin partidos --
                                    # no se marca como "completo" para que los reintentos (04:00-05:59) sigan insistiendo
            and all(p.get("fuente_favorito") in FUENTES_VALIDAS for p in partidos)
        )
    except (json.JSONDecodeError, OSError):
        return False


def _archivar_dia_anterior(datos_previos):
    """Si la fecha cambio (nuevo dia local), archiva el dia anterior
    completo (resultados, historial_dias/, Excel) ANTES de pisar
    partidos_hoy.json. Sin esto el cierre dependia de que el cron de la
    Fase 4 cayera dentro de la ventana 00:00-05:00 local: con los crons
    de GitHub atrasados horas se archivaba la fecha recien empezada (con
    0 snapshots) o directamente se perdia el dia."""
    if not datos_previos or datos_previos.get("fecha") == fecha_local_hoy():
        return
    if not datos_previos.get("partidos"):
        return
    try:
        import cerrar_resultados
        cerrar_resultados.cerrar(datos=datos_previos, escribir_partidos=False)
    except Exception as error:
        print(f"[AVISO] No se pudo archivar el dia {datos_previos.get('fecha')}: {error}")


def _normalizar_equipo(nombre):
    nombre_norm = normalizar(nombre)
    equivalente_aprendido = _cargar_cache_alias().get(nombre_norm)
    if equivalente_aprendido:
        nombre_norm = normalizar(equivalente_aprendido)
    nombre_norm = " ".join(palabra for palabra in nombre_norm.split() if palabra not in SUFIJOS_EQUIPO)
    return ALIAS_EQUIPOS.get(nombre_norm, nombre_norm)


def _coincide(nombre_hoja, nombre_espn):
    a, b = _normalizar_equipo(nombre_hoja), _normalizar_equipo(nombre_espn)
    return bool(a and b and (a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.82))


def _tipo_pronostico(favorito_hoja):
    """La hoja marca la doble oportunidad con el prefijo 'DC' (ej. 'DC
    LOCAL', 'DC VISITANTE'). El lado (local/visitante) que va dentro de
    ese texto ya viene decidido por quien llena la hoja -- es el lado
    de la doble oportunidad que consideraron mas probable (ej. 'DC
    LOCAL' = local o empate). _lado_favorito() ya lo detecta bien
    porque compara por palabra, no por texto exacto -- aqui solo se
    distingue si es 'directo' o 'doble_oportunidad' para poder avisarlo
    al inicio de cada mensaje."""
    palabras = set(normalizar(favorito_hoja).split())
    return "doble_oportunidad" if "dc" in palabras else "favorito_directo"


def _lado_favorito(favorito_hoja, local, visitante):
    favorito = normalizar(favorito_hoja)
    palabras = set(favorito.split())
    if favorito in {"local", "home", "1"} or "local" in palabras or "home" in palabras or _coincide(favorito_hoja, local):
        return "local"
    if favorito in {"visitante", "away", "2"} or "visitante" in palabras or "away" in palabras or _coincide(favorito_hoja, visitante):
        return "visitante"
    return None


def _coincide_con_alternativas(nombre_hoja, nombre_espn):
    """Coincidencia directa (normalizacion + fuzzy) y, si esa falla,
    contra los nombres alternativos que reporte TheSportsDB para el
    nombre de la hoja (ej. 'Viborg' -> 'Viborg FF', 'Wolves' ->
    'Wolverhampton Wanderers')."""
    if _coincide(nombre_hoja, nombre_espn):
        return True
    return any(_coincide(alternativo, nombre_espn) for alternativo in nombres_alternativos(nombre_hoja))


def _buscar_fixture(entrada, fixtures):
    candidatos = [f for f in fixtures if _coincide(entrada["local"], f["teams"]["home"]["name"]) and _coincide(entrada["visitante"], f["teams"]["away"]["name"])]
    if len(candidatos) == 1:
        return candidatos[0]

    # Segundo intento: se prueban los nombres alternativos de
    # TheSportsDB en AMBOS lados de forma independiente (antes solo se
    # probaba en el lado que no habia coincidido directo, asumiendo que
    # el otro si coincidia -- eso dejaba sin cubrir el caso de que los
    # DOS nombres de la hoja difirieran del oficial de ESPN).
    candidatos = [
        f for f in fixtures
        if _coincide_con_alternativas(entrada["local"], f["teams"]["home"]["name"])
        and _coincide_con_alternativas(entrada["visitante"], f["teams"]["away"]["name"])
    ]
    if len(candidatos) != 1:
        return None

    fixture = candidatos[0]
    # Se encontro por un camino no trivial -- se aprende el alias para
    # que el proximo dia sea un match directo sin volver a depender de
    # TheSportsDB ni del fuzzy match.
    _registrar_alias_aprendido(entrada["local"], fixture["teams"]["home"]["name"])
    _registrar_alias_aprendido(entrada["visitante"], fixture["teams"]["away"]["name"])
    return fixture


def _buscar_fixture_por_id(entrada, fixtures):
    """Matching exacto por fixture_id, para las entradas que lo traen
    (elo-tilt usa el mismo id de ESPN, asi que no hace falta fuzzy
    match ni TheSportsDB). Las hojas de Google Sheets no traen id, asi
    que para ellas esto devuelve None y sigue el camino por nombres."""
    fid = str(entrada.get("fixture_id") or "")
    if not fid:
        return None
    for fixture in fixtures:
        if str(fixture["fixture"]["id"]) == fid:
            return fixture
    return None


def _partido_para_vigilar(fixture, favorito_hoja, fila_hoja, confianza_estrellas=0,
                           cuota_local=None, cuota_empate=None, cuota_visitante=None,
                           prioridad="ALTA", fuente="Google Sheets"):
    local, visitante = fixture["teams"]["home"], fixture["teams"]["away"]
    lado = _lado_favorito(favorito_hoja, local["name"], visitante["name"])
    if lado is None:
        return None
    favorito = local["name"] if lado == "local" else visitante["name"]
    no_favorito = visitante["name"] if lado == "local" else local["name"]
    return {
        "partido": f"{local['name']} vs {visitante['name']}", "local": local["name"], "visitante": visitante["name"],
        "favorito": favorito, "no_favorito": no_favorito, "favorito_es_local": lado == "local",
        "tipo_pronostico": _tipo_pronostico(favorito_hoja), "confianza_estrellas": confianza_estrellas,
        "cuota_local_inicial": cuota_local, "cuota_empate_inicial": cuota_empate, "cuota_visitante_inicial": cuota_visitante,
        "prioridad": prioridad,
        "fuente_favorito": fuente, "fila_fuente": fila_hoja,
        "hora_inicio": fixture["fixture"]["date"], "fixture_id": fixture["fixture"]["id"], "liga_slug": fixture.get("_liga_slug"),
        "liga_pais": fixture.get("league", {}).get("country", ""), "liga_nombre": fixture.get("league", {}).get("name", ""),
        "home_id": local["id"], "away_id": visitante["id"], "kickoff_utc": fixture["fixture"]["date"],
        "resultado_final": None, "acierto": None, "historial_snapshots": [], "alertas_enviadas": [], "diferencia_maxima_alcanzada": 0,
    }


def seleccionar(forzar=False):
    """forzar=True se usa en la revision de las 19:00 (a pedido
    explicito, agosto 2026): ignora ya_se_completo_hoy() para volver a
    leer la hoja por si se subieron cambios durante el dia. Pero NO
    sobreescribe de golpe -- FUSIONA por fixture_id: los partidos que
    ya estaban (posiblemente con horas de seguimiento en vivo
    acumuladas, alertas enviadas, etc.) se conservan tal cual, y solo
    se agregan los que sean nuevos en la hoja. Sobreescribir sin
    fusionar borraria el historial de partidos que ya estan en curso o
    ya jugaron parte del primer tiempo."""
    if not forzar and ya_se_completo_hoy():
        print("La selección de hoy ya se generó antes. Nada que hacer.")
        return
    hoy = fecha_local_hoy()
    fuente = "Google Sheets"
    try:
        favoritos = obtener_favoritos_google(hoy=datetime.date.fromisoformat(hoy))
    except Exception as error:
        print(f"[AVISO] No se pudieron leer los favoritos de Google Sheets: {error}")
        favoritos = []
    print(f"Google Sheets: {len(favoritos)} favorito(s) válido(s) para procesar.")
    if not favoritos:
        favoritos = obtener_favoritos_elo_tilt(hoy=datetime.date.fromisoformat(hoy))
        fuente = "elo-tilt"
        print(f"elo-tilt (respaldo): {len(favoritos)} favorito(s) válido(s) para procesar.")
    if not favoritos:
        print("[ERROR] Ninguna fuente devolvió favoritos para hoy (Google Sheets y elo-tilt).")
        return
    fixtures = obtener_fixtures_por_fecha(hoy)
    seleccionados, sin_fixture, favorito_invalido, vistos = [], 0, 0, set()
    for entrada in favoritos:
        fixture = _buscar_fixture_por_id(entrada, fixtures) or _buscar_fixture(entrada, fixtures)
        if fixture is None:
            sin_fixture += 1
            print(f"[AVISO] Fila {entrada['fila_hoja']}: no se encontró en ESPN: {entrada['local']} vs {entrada['visitante']}")
            _registrar_pendiente(entrada, "no_encontrado_en_espn", hoy)
            continue
        partido = _partido_para_vigilar(
            fixture, entrada["favorito"], entrada["fila_hoja"], entrada.get("confianza_estrellas", 0),
            cuota_local=entrada.get("cuota_local"), cuota_empate=entrada.get("cuota_empate"),
            cuota_visitante=entrada.get("cuota_visitante"),
            prioridad=entrada.get("prioridad", "ALTA"),
            fuente=fuente,
        )
        if partido is None:
            favorito_invalido += 1
            print(f"[AVISO] Fila {entrada['fila_hoja']}: favorito inválido: {entrada['favorito']}")
            continue
        if partido["fixture_id"] not in vistos:
            seleccionados.append(partido)
            vistos.add(partido["fixture_id"])
    seleccionados.sort(key=lambda partido: partido["hora_inicio"])

    datos_previos = None
    if ARCHIVO_SALIDA.exists():
        try:
            datos_previos = json.loads(ARCHIVO_SALIDA.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            datos_previos = None

    # La fecha cambio (nuevo dia local): primero se archiva el dia viejo
    # con todos sus datos; recien despues se pisa partidos_hoy.json.
    _archivar_dia_anterior(datos_previos)

    if not seleccionados and datos_previos and datos_previos.get("fecha") == hoy \
            and datos_previos.get("partidos"):
        # 0 partidos validos casi siempre es un fallo transitorio de la
        # fuente: no se pisa el seguimiento en curso del dia.
        print("[AVISO] La fuente no produjo partidos válidos con fixture en ESPN; se conserva la selección existente de hoy.")
        return

    nuevos_en_revision = None
    if forzar and datos_previos and datos_previos.get("fecha") == hoy:
        previos_por_id = {p["fixture_id"]: p for p in datos_previos.get("partidos", [])}
        fusionados = []
        for nuevo in seleccionados:
            fid = nuevo["fixture_id"]
            previo = previos_por_id.get(fid)
            if previo is None:
                fusionados.append(nuevo)
                continue
            # Conserva historial si ya existia, pero repara el
            # liga_slug si el previo quedo con "all" (no sirve para
            # el summary en vivo) y el nuevo trae el slug real.
            if (not previo.get("liga_slug") or previo.get("liga_slug") == "all") \
                    and nuevo.get("liga_slug") not in (None, "", "all"):
                previo["liga_slug"] = nuevo["liga_slug"]
            if not previo.get("liga_nombre") and nuevo.get("liga_nombre"):
                previo["liga_pais"] = nuevo.get("liga_pais", "")
                previo["liga_nombre"] = nuevo.get("liga_nombre", "")
            fusionados.append(previo)  # conserva historial si ya existia
        nuevos_en_revision = sum(1 for p in seleccionados if p["fixture_id"] not in previos_por_id)
        seleccionados = fusionados

    ARCHIVO_SALIDA.write_text(json.dumps({"fecha": hoy, "seleccion_version": VERSION_SELECCION, "partidos": seleccionados}, ensure_ascii=False, indent=2), encoding="utf-8")
    if nuevos_en_revision is not None:
        print(f"Revision de la noche: {len(seleccionados)} partido(s) en total, {nuevos_en_revision} nuevo(s) agregado(s), "
              f"el resto conserva su seguimiento en vivo ya acumulado.")
    print(f"Guardado en {ARCHIVO_SALIDA}: {len(seleccionados)} partido(s) de {fuente}. Sin fixture: {sin_fixture}; favorito inválido: {favorito_invalido}.")


if __name__ == "__main__":
    seleccionar(forzar="--forzar" in sys.argv)

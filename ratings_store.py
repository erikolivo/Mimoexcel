"""
ratings_store.py
-----------------
Guarda y actualiza el "rating propio" (Glicko-2) de cada equipo, y
decide como MEZCLARLO con el Elo de ClubElo.

CAMBIO por la migracion a ESPN (agosto 2026): la llave primaria de
equipo cambio de "id:<team_id_api_football>" a "espn:<team_id_espn>".
Esto NO es cosmetico -- API-Football y ESPN tienen sistemas de IDs
completamente distintos, y en al menos un caso confirmado durante la
migracion (Arsenal) el ID numerico coincidio por pura casualidad entre
ambos sistemas. Reusar el mismo prefijo "id:" habria arriesgado FUSIONAR
el historial de dos equipos distintos sin darse cuenta. Por eso el
prefijo "espn:" es nuevo y exclusivo, y migrar_api_football_a_espn()
existe para trasladar el historial viejo por NOMBRE (no por ID) hacia
la llave nueva, sin arriesgar una colision silenciosa.

Decision de diseno (sin cambios, confirmada explicitamente): ClubElo es
la SEMILLA de arranque, nunca se reemplaza por completo -- pero a
medida que el sistema observa partidos reales, el peso se desplaza
hacia el rating propio. Un equipo con 1 solo partido observado YA
aporta al blend.

Tabla de pesos (rating propio) segun partidos propios observados (n):
    n == 0        ->   0%  (kilometro cero: puro ClubElo)
    n in 1..3     ->  20%
    n in 4..8     ->  50%
    n in 9..15    ->  75%
    n > 15        -> 100%
"""

import json
import datetime
from pathlib import Path

import glicko2

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_RATINGS = DATA_DIR / "ratings_propios.json"

TRAMOS_PESO = [
    (0, 0.0),
    (3, 0.20),
    (8, 0.50),
    (15, 0.75),
]
PESO_MAXIMO = 1.0


def peso_rating_propio(n_partidos):
    for tope, peso in TRAMOS_PESO:
        if n_partidos <= tope:
            return peso
    return PESO_MAXIMO


def _cargar():
    if ARCHIVO_RATINGS.exists():
        try:
            return json.loads(ARCHIVO_RATINGS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"equipos": {}}


def _guardar(datos):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVO_RATINGS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def llave_equipo(team_id, pais=None, nombre=None):
    """CAMBIO: prefijo 'espn:' (antes 'id:') -- ver docstring del
    modulo para el motivo (evitar colision de IDs entre proveedores)."""
    if team_id:
        return f"espn:{team_id}"
    return f"np:{pais or '?'}|{nombre or '?'}"


def obtener_o_crear(llave, nombre=None, pais=None, liga=None):
    datos = _cargar()
    equipo = datos["equipos"].get(llave)
    if equipo is None:
        equipo = {
            "nombre": nombre, "pais": pais, "liga": liga,
            "rating": glicko2.RATING_BASE, "rd": glicko2.RD_INICIAL, "vol": glicko2.VOL_INICIAL,
            "partidos_jugados": 0, "partidos_bootstrap": 0, "partidos_reales": 0,
            "ultima_actualizacion": None,
        }
        datos["equipos"][llave] = equipo
        _guardar(datos)
    return equipo


def actualizar_tras_partido(llave, rating_rival, rd_rival, resultado, es_bootstrap=False, fecha=None):
    datos = _cargar()
    eq = datos["equipos"].get(llave)
    if eq is None:
        eq = obtener_o_crear(llave)
        datos = _cargar()
        eq = datos["equipos"][llave]

    nuevo_rating, nuevo_rd, nuevo_vol = glicko2.actualizar_rating(
        eq["rating"], eq["rd"], eq["vol"], [(rating_rival, rd_rival, resultado)]
    )
    eq["rating"], eq["rd"], eq["vol"] = nuevo_rating, nuevo_rd, nuevo_vol
    eq["partidos_jugados"] = eq.get("partidos_jugados", 0) + 1
    if es_bootstrap:
        eq["partidos_bootstrap"] = eq.get("partidos_bootstrap", 0) + 1
    else:
        eq["partidos_reales"] = eq.get("partidos_reales", 0) + 1
    eq["ultima_actualizacion"] = (fecha or datetime.date.today().isoformat())

    datos["equipos"][llave] = eq
    _guardar(datos)
    return eq


def rating_combinado(llave, elo_clubelo, nombre=None, pais=None, liga=None):
    eq = obtener_o_crear(llave, nombre=nombre, pais=pais, liga=liga)
    n = eq.get("partidos_reales", 0) + eq.get("partidos_bootstrap", 0)
    peso_propio = peso_rating_propio(n)

    if elo_clubelo is None:
        return eq["rating"], n, eq["rd"]

    rating_final = peso_propio * eq["rating"] + (1 - peso_propio) * elo_clubelo
    return round(rating_final, 2), n, eq["rd"]


def rd_de(llave):
    eq = obtener_o_crear(llave)
    return eq["rd"]


def migrar_bootstrap_a_id(nombre, team_id, liga=None, corte=0.85):
    """Sin cambios de logica -- solo se beneficia del nuevo prefijo
    'espn:' via llave_equipo(). Fusiona un registro de bootstrap
    ('boot:liga|nombre') con la llave definitiva del equipo cuando
    aparece por primera vez en un fixture real."""
    import difflib as _difflib

    llave_final = llave_equipo(team_id)
    datos = _cargar()
    if llave_final in datos["equipos"] and datos["equipos"][llave_final].get("partidos_jugados", 0) > 0:
        return

    candidatos = {
        k: v for k, v in datos["equipos"].items()
        if k.startswith("boot:") and not v.get("_fusionado")
        and (liga is None or v.get("liga") == liga)
    }
    if not candidatos:
        return

    nombres = {k: v.get("nombre", "") for k, v in candidatos.items()}
    match = _difflib.get_close_matches(nombre, list(nombres.values()), n=1, cutoff=corte)
    if not match:
        return

    llave_bootstrap = next(k for k, v in nombres.items() if v == match[0])
    origen = datos["equipos"][llave_bootstrap]

    datos["equipos"][llave_final] = {
        "nombre": nombre, "pais": origen.get("pais"), "liga": origen.get("liga"),
        "rating": origen["rating"], "rd": origen["rd"], "vol": origen["vol"],
        "partidos_jugados": origen.get("partidos_jugados", 0),
        "partidos_bootstrap": origen.get("partidos_bootstrap", 0),
        "partidos_reales": 0,
        "ultima_actualizacion": origen.get("ultima_actualizacion"),
    }
    datos["equipos"][llave_bootstrap]["_fusionado"] = llave_final
    _guardar(datos)
    print(f"[INFO] Rating de bootstrap fusionado para '{nombre}' (desde '{match[0]}').")


def migrar_api_football_a_espn(nombre, team_id_espn, liga=None, corte=0.88):
    """
    NUEVO -- exclusivo de esta migracion. Busca, entre los registros
    VIEJOS (llave que empieza con 'id:', el prefijo que usaba
    API-Football), uno cuyo nombre coincida muy de cerca con 'nombre'
    (corte alto a proposito: mejor no fusionar que fusionar mal, MISMO
    criterio que ya usaba migrar_bootstrap_a_id) y, si lo encuentra,
    copia su historial de Glicko-2 a la llave nueva 'espn:<team_id>'.

    Se llama UNA VEZ por equipo, la primera vez que aparece en un
    fixture de ESPN (mismo patron que la migracion de bootstrap). El
    registro viejo se conserva marcado como fusionado, no se borra --
    trazabilidad, igual que con el bootstrap.
    """
    import difflib as _difflib

    llave_final = llave_equipo(team_id_espn)
    datos = _cargar()
    if llave_final in datos["equipos"] and datos["equipos"][llave_final].get("partidos_jugados", 0) > 0:
        return  # ya tiene vida propia bajo ESPN, no pisar

    candidatos = {
        k: v for k, v in datos["equipos"].items()
        if k.startswith("id:") and not v.get("_fusionado")
        and (liga is None or v.get("liga") == liga)
    }
    if not candidatos:
        return

    nombres = {k: v.get("nombre", "") for k, v in candidatos.items()}
    match = _difflib.get_close_matches(nombre, list(nombres.values()), n=1, cutoff=corte)
    if not match:
        return

    llave_vieja = next(k for k, v in nombres.items() if v == match[0])
    origen = datos["equipos"][llave_vieja]

    datos["equipos"][llave_final] = {
        "nombre": nombre, "pais": origen.get("pais"), "liga": origen.get("liga"),
        "rating": origen["rating"], "rd": origen["rd"], "vol": origen["vol"],
        "partidos_jugados": origen.get("partidos_jugados", 0),
        "partidos_bootstrap": origen.get("partidos_bootstrap", 0),
        "partidos_reales": origen.get("partidos_reales", 0),
        "ultima_actualizacion": origen.get("ultima_actualizacion"),
    }
    datos["equipos"][llave_vieja]["_fusionado"] = llave_final
    _guardar(datos)
    print(f"[INFO] Historial pre-ESPN fusionado para '{nombre}' (desde '{match[0]}').")

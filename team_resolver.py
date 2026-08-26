"""
team_resolver.py
------------------
Resuelve, para cada equipo, su PAIS REAL (no el pais de la liga del
fixture) y lo cachea para siempre.

CAMBIO por la migracion a ESPN: la funcion resolver_pais_equipo() ya no
consulta cuota_api_football.uso_de_hoy() para decidir si hay cupo (ese
modulo ya no existe -- ver cuota_espn.py). ESPN no tiene un limite
diario conocido contra el cual reservar margen, asi que el chequeo se
simplifica a solo el tope de resoluciones POR CORRIDA (sigue siendo una
red de seguridad razonable contra bugs, no una proteccion de cupo).
Ademas, esta via ahora es tier 3 (ultimo recurso) en _resolver_pais()
de seleccionar_partidos.py -- ESPN no da nacionalidad de club tan
directo como API-Football, asi que se prioriza mas la liga domestica y
el Goal Index (ver fetch_data.obtener_info_equipo).

Todo lo demas -- la correccion de PAIS_A_CODIGO_CLUBELO y la
verificacion cruzada por confederacion (opcion B) -- sigue igual, no
depende de que proveedor de datos en vivo se use.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_CACHE = DATA_DIR / "team_country_cache.json"

PAIS_A_CODIGO_CLUBELO = {
    "England": "ENG", "Scotland": "SCO", "Wales": "WAL", "Northern-Ireland": "NIR",
    "Spain": "ESP", "Italy": "ITA", "Germany": "GER", "France": "FRA",
    "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Turkey": "TUR",
    "Greece": "GRE", "Russia": "RUS", "Ukraine": "UKR", "Poland": "POL",
    "Austria": "AUT", "Switzerland": "SUI", "Sweden": "SWE", "Norway": "NOR",
    "Denmark": "DEN", "Finland": "FIN", "Iceland": "ISL", "Ireland": "IRL",
    "Croatia": "CRO", "Serbia": "SRB", "Romania": "ROU", "Bulgaria": "BUL",
    "Hungary": "HUN", "Czech-Republic": "CZE", "Slovakia": "SVK", "Slovenia": "SVN",
    "Bosnia": "BIH", "Israel": "ISR", "Cyprus": "CYP", "Luxembourg": "LUX",
    "Brazil": "BRA", "Argentina": "ARG", "Mexico": "MEX", "USA": "USA",
    "Colombia": "COL", "Chile": "CHI", "Peru": "PER", "Uruguay": "URU",
    "Ecuador": "ECU", "Paraguay": "PAR", "Bolivia": "BOL", "Venezuela": "VEN",
    "Australia": "AUS", "Japan": "JPN", "South-Korea": "KOR", "China": "CHN",
    "Saudi-Arabia": "KSA", "Qatar": "QAT", "Egypt": "EGY", "South-Africa": "RSA",
}

CONFEDERACION_POR_PAIS = {
    "Brazil": "CONMEBOL", "Argentina": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Paraguay": "CONMEBOL", "Chile": "CONMEBOL", "Colombia": "CONMEBOL",
    "Ecuador": "CONMEBOL", "Peru": "CONMEBOL", "Bolivia": "CONMEBOL",
    "Venezuela": "CONMEBOL",
    "England": "UEFA", "Spain": "UEFA", "Italy": "UEFA", "Germany": "UEFA",
    "France": "UEFA", "Portugal": "UEFA", "Netherlands": "UEFA",
    "Belgium": "UEFA", "Scotland": "UEFA", "Turkey": "UEFA", "Greece": "UEFA",
    "Russia": "UEFA", "Ukraine": "UEFA", "Poland": "UEFA", "Austria": "UEFA",
    "Switzerland": "UEFA", "Sweden": "UEFA", "Norway": "UEFA", "Denmark": "UEFA",
    "Croatia": "UEFA", "Serbia": "UEFA", "Romania": "UEFA",
    "Mexico": "CONCACAF", "USA": "CONCACAF", "Costa-Rica": "CONCACAF",
    "Honduras": "CONCACAF", "Panama": "CONCACAF",
    "Japan": "AFC", "South-Korea": "AFC", "China": "AFC", "Saudi-Arabia": "AFC",
    "Qatar": "AFC", "Egypt": "CAF", "South-Africa": "CAF", "Morocco": "CAF",
}


def _cargar():
    if ARCHIVO_CACHE.exists():
        try:
            return json.loads(ARCHIVO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _guardar(cache):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def confederacion_de(pais):
    return CONFEDERACION_POR_PAIS.get(pais)


def codigo_clubelo_de(pais):
    return PAIS_A_CODIGO_CLUBELO.get(pais)


LIMITE_RESOLUCIONES_POR_CORRIDA_DEFECTO = 25

_limite_efectivo_esta_corrida = LIMITE_RESOLUCIONES_POR_CORRIDA_DEFECTO
_contador_resoluciones_esta_corrida = 0


def resetear_contador_corrida(limite=None):
    global _contador_resoluciones_esta_corrida, _limite_efectivo_esta_corrida
    _contador_resoluciones_esta_corrida = 0
    _limite_efectivo_esta_corrida = limite if limite is not None else LIMITE_RESOLUCIONES_POR_CORRIDA_DEFECTO


def resolver_pais_equipo(team_id, nombre_fallback, obtener_info_equipo_fn):
    """
    CAMBIO: ya no consulta un cupo diario conocido (ver docstring del
    modulo) -- solo respeta el tope de resoluciones por corrida, como
    red de seguridad generica contra bugs, no como proteccion de cupo.
    """
    global _contador_resoluciones_esta_corrida

    cache = _cargar()
    entrada = cache.get(str(team_id))
    if entrada:
        return entrada["pais"]

    if _contador_resoluciones_esta_corrida >= _limite_efectivo_esta_corrida:
        return None

    try:
        info = obtener_info_equipo_fn(team_id)
    except Exception as e:
        print(f"[AVISO] No se pudo resolver el pais del equipo {nombre_fallback} (id {team_id}): {e}")
        _contador_resoluciones_esta_corrida += 1
        return None

    _contador_resoluciones_esta_corrida += 1

    if not info:
        return None

    pais = info.get("country")
    cache[str(team_id)] = {"nombre": nombre_fallback, "pais": pais}
    _guardar(cache)
    return pais


def elegir_candidato_verificado(nombre, pais_equipo, elo_por_pais, elo_global, buscar_similar_fn,
                                 pais_rival=None):
    codigo_equipo = codigo_clubelo_de(pais_equipo) if pais_equipo else None
    if codigo_equipo and codigo_equipo in elo_por_pais:
        candidatos = list(elo_por_pais[codigo_equipo].keys())
        match = buscar_similar_fn(nombre, candidatos, n=1, corte=0.6)
        if match:
            return elo_por_pais[codigo_equipo][match[0]], True, "pais_propio"

    if pais_rival:
        confed_rival = confederacion_de(pais_rival)
        if confed_rival:
            paises_confed = [p for p, c in CONFEDERACION_POR_PAIS.items() if c == confed_rival]
            candidatos = []
            mapa_candidato_a_codigo = {}
            for p in paises_confed:
                codigo_p = codigo_clubelo_de(p)
                if not codigo_p:
                    continue
                for club in elo_por_pais.get(codigo_p, {}):
                    candidatos.append(club)
                    mapa_candidato_a_codigo[club] = codigo_p
            match = buscar_similar_fn(nombre, candidatos, n=1, corte=0.6)
            if match:
                codigo_encontrado = mapa_candidato_a_codigo[match[0]]
                return elo_por_pais[codigo_encontrado][match[0]], True, "verificacion_cruzada"

    candidatos_global = list(elo_global.keys())
    match = buscar_similar_fn(nombre, candidatos_global, n=1, corte=0.6)
    if match:
        return elo_global[match[0]], False, "global_sin_verificar"

    return None, False, "sin_match"

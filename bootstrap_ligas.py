"""
bootstrap_ligas.py
--------------------
SIN CAMBIOS por la migracion a ESPN -- usa football-data.co.uk, que no
tiene nada que ver con API-Football ni con ESPN.

Se corre MANUALMENTE cuando aparece una liga nueva o se quiere reforzar
el rating propio de una liga existente con mas historia. Reproduce las
ultimas 1-2 temporadas EN ORDEN CRONOLOGICO a traves de Glicko-2.

Uso:
    python bootstrap_ligas.py E0 SP1 I1
    python bootstrap_ligas.py --extra ARG BRA
"""

import argparse
import datetime

import ratings_store
import team_resolver
from poisson_model import VENTAJA_LOCAL_ELO
from fetch_data import (
    obtener_resultados_liga_multi_temporada,
    obtener_resultados_liga_extra,
    obtener_ranking_clubelo,
    CODIGO_LIGA_A_PAIS,
    buscar_equipo_similar,
    LIGAS_FOOTBALL_DATA,
    LIGAS_FOOTBALL_DATA_EXTRA,
)

TEMPORADAS_BOOTSTRAP = ["2425", "2526"]


def _llave_bootstrap(nombre_equipo, liga):
    return f"boot:{liga}|{nombre_equipo}"


def bootstrap_liga_principal(codigo_liga):
    print(f"Bootstrap de {codigo_liga} ({LIGAS_FOOTBALL_DATA.get(codigo_liga, codigo_liga)})...")
    partidos = obtener_resultados_liga_multi_temporada(codigo_liga, TEMPORADAS_BOOTSTRAP)
    _reproducir_partidos(partidos, codigo_liga)
    calibrar_liga(codigo_liga)


def bootstrap_liga_extra(codigo_liga):
    print(f"Bootstrap de liga extra {codigo_liga} ({LIGAS_FOOTBALL_DATA_EXTRA.get(codigo_liga, codigo_liga)})...")
    partidos = obtener_resultados_liga_extra(codigo_liga)
    _reproducir_partidos(partidos, codigo_liga)
    calibrar_liga(codigo_liga)


def _reproducir_partidos(partidos, liga):
    procesados = 0
    for p in partidos:
        home, away = p.get("HomeTeam"), p.get("AwayTeam")
        if not home or not away:
            continue
        try:
            gh, ga = int(p["FTHG"]), int(p["FTAG"])
        except (KeyError, ValueError):
            continue

        llave_home = _llave_bootstrap(home, liga)
        llave_away = _llave_bootstrap(away, liga)

        eq_home = ratings_store.obtener_o_crear(llave_home, nombre=home, liga=liga)
        eq_away = ratings_store.obtener_o_crear(llave_away, nombre=away, liga=liga)

        if gh > ga:
            resultado_home, resultado_away = 1.0, 0.0
        elif gh < ga:
            resultado_home, resultado_away = 0.0, 1.0
        else:
            resultado_home, resultado_away = 0.5, 0.5

        rating_home_antes, rd_home_antes = eq_home["rating"], eq_home["rd"]
        rating_away_antes, rd_away_antes = eq_away["rating"], eq_away["rd"]

        # Tarea 8: misma ventaja de local que poisson_model (sin
        # duplicar la constante); sede neutral: sin ajuste.
        ajuste = 0 if p.get("neutral") else VENTAJA_LOCAL_ELO

        ratings_store.actualizar_tras_partido(llave_home, rating_away_antes - ajuste, rd_away_antes,
                                               resultado_home, es_bootstrap=True, fecha=p.get("Date"))
        ratings_store.actualizar_tras_partido(llave_away, rating_home_antes + ajuste, rd_home_antes,
                                               resultado_away, es_bootstrap=True, fecha=p.get("Date"))
        procesados += 1

    print(f"  {procesados} partidos reproducidos.")


def pares_elo_desde_ranking(filas, equipos, codigo_liga):
    """Empareja los equipos del store con el ranking de ClubElo.

    `filas` son las filas del CSV de ClubElo ({Club, Country, Rating}),
    `equipos` es {llave: nombre} de los equipos de la liga. Usa la
    logica existente de team_resolver.elegir_candidato_verificado, con
    el filtro por pais incluido. Devuelve {llave: elo_clubelo}.
    """
    elo_global, elo_por_pais = {}, {}
    for fila in filas:
        club = fila.get("Club")
        if not club:
            continue
        bruto = fila.get("Rating") or fila.get("Elo")
        try:
            rating = float(bruto)
        except (TypeError, ValueError):
            continue
        elo_global[club] = rating
        pais = fila.get("Country")
        if pais:
            elo_por_pais.setdefault(pais, {})[club] = rating

    pais_liga = CODIGO_LIGA_A_PAIS.get(codigo_liga)
    pares = {}
    for llave, nombre in equipos.items():
        if not nombre:
            continue
        rating, _encontrado, _metodo = team_resolver.elegir_candidato_verificado(
            nombre, pais_liga, elo_por_pais, elo_global, buscar_equipo_similar)
        if rating is not None:
            pares[llave] = rating
    return pares


def calibrar_liga(codigo_liga):
    """Descarga el ranking de ClubElo de hoy y calibra la escala de la
    liga en el store (sin reproducir partidos)."""
    datos = ratings_store._cargar()
    equipos = {k: v.get("nombre") for k, v in datos["equipos"].items()
               if v.get("liga") == codigo_liga and k.startswith("boot:")}
    if not equipos:
        print(f"[AVISO] Calibracion {codigo_liga}: no hay equipos "
              "bootstrapeados de esa liga.")
        return None
    filas = obtener_ranking_clubelo(datetime.date.today().isoformat())
    if not filas:
        print(f"[AVISO] Calibracion {codigo_liga}: ranking de ClubElo "
              "vacio (no se pudo descargar); no se calibra.")
        return None
    pares = pares_elo_desde_ranking(filas, equipos, codigo_liga)
    if not pares:
        print(f"[AVISO] Calibracion {codigo_liga}: ningun equipo emparejado "
              "con ClubElo; no se calibra.")
        return None
    return ratings_store.calibrar_liga_a_clubelo(codigo_liga, pares)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap del rating propio para una o mas ligas.")
    parser.add_argument("codigos", nargs="+", help="Codigos de liga (ej. E0 SP1) o de liga extra con --extra")
    parser.add_argument("--extra", action="store_true", help="Trata los codigos como ligas 'extra'")
    parser.add_argument("--calibrar", action="store_true",
                        help="Solo calibra la escala contra ClubElo (no reproduce partidos)")
    args = parser.parse_args()

    for codigo in args.codigos:
        if args.calibrar:
            calibrar_liga(codigo)
        elif args.extra:
            bootstrap_liga_extra(codigo)
        else:
            bootstrap_liga_principal(codigo)

    print("Bootstrap completo." if not args.calibrar else "Calibracion completa.")

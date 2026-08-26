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

import ratings_store
from fetch_data import (
    obtener_resultados_liga_multi_temporada,
    obtener_resultados_liga_extra,
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


def bootstrap_liga_extra(codigo_liga):
    print(f"Bootstrap de liga extra {codigo_liga} ({LIGAS_FOOTBALL_DATA_EXTRA.get(codigo_liga, codigo_liga)})...")
    partidos = obtener_resultados_liga_extra(codigo_liga)
    _reproducir_partidos(partidos, codigo_liga)


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

        ratings_store.actualizar_tras_partido(llave_home, rating_away_antes, rd_away_antes,
                                               resultado_home, es_bootstrap=True, fecha=p.get("Date"))
        ratings_store.actualizar_tras_partido(llave_away, rating_home_antes, rd_home_antes,
                                               resultado_away, es_bootstrap=True, fecha=p.get("Date"))
        procesados += 1

    print(f"  {procesados} partidos reproducidos.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap del rating propio para una o mas ligas.")
    parser.add_argument("codigos", nargs="+", help="Codigos de liga (ej. E0 SP1) o de liga extra con --extra")
    parser.add_argument("--extra", action="store_true", help="Trata los codigos como ligas 'extra'")
    args = parser.parse_args()

    for codigo in args.codigos:
        if args.extra:
            bootstrap_liga_extra(codigo)
        else:
            bootstrap_liga_principal(codigo)

    print("Bootstrap completo.")

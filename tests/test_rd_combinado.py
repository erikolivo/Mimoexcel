"""Tarea 5: el RD devuelto por rating_combinado describe el rating
COMBINADO, para que aplicar_rd() no borre la senal de ClubElo."""
import json

import ratings_store
from poisson_model import aplicar_rd


def _guardar_equipo(archivo, llave, rating, rd, reales=0, bootstrap=0):
    archivo.write_text(json.dumps({"equipos": {llave: {
        "nombre": "Equipo", "pais": None, "liga": None,
        "rating": rating, "rd": rd, "vol": 0.06,
        "partidos_jugados": reales + bootstrap,
        "partidos_bootstrap": bootstrap, "partidos_reales": reales,
        "ultima_actualizacion": "2026-01-01",
    }}}), encoding="utf-8")


def test_cero_partidos_clubelo_no_se_encoge(ratings_tmp):
    rating, n, rd = ratings_store.rating_combinado("espn:99", 1800.0,
                                                   nombre="Nuevo FC")
    assert n == 0
    assert round(aplicar_rd(rating, rd), 2) == 1800.0


def test_peso_propio_total_rd_350_si_encoge(ratings_tmp):
    _guardar_equipo(ratings_tmp, "espn:77", 1800.0, 350.0, reales=20)
    rating, n, rd = ratings_store.rating_combinado("espn:77", 1800.0)
    assert n == 20
    assert rd == 350.0
    assert aplicar_rd(rating, rd) == 1500.0


def test_peso_intermedio_interpola_el_rd(ratings_tmp):
    _guardar_equipo(ratings_tmp, "espn:78", 1600.0, 120.0, reales=4)
    rating, n, rd = ratings_store.rating_combinado("espn:78", 1800.0)
    assert n == 4
    assert rating == 1700.0   # 50% propio (1600) + 50% ClubElo (1800)
    assert rd == 85.0         # 50% de 120 + 50% de RD_EFECTIVO_CLUBELO (50)


def test_sin_elo_mantiene_rating_y_rd_propios(ratings_tmp):
    rating, n, rd = ratings_store.rating_combinado("espn:5", None,
                                                   nombre="Solo Propio")
    assert rating == ratings_store.glicko2.RATING_BASE
    assert rd == ratings_store.glicko2.RD_INICIAL
    assert n == 0

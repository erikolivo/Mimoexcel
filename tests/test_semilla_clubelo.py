"""Tarea 6a: los equipos nuevos (o registros vacios antiguos) se
siembran con el Elo de ClubElo en lugar de arrancar en 1500/350."""
import json

import ratings_store


def _registro_vacio(ratings_tmp, llave, rating=1500.0, rd=350.0, jugados=0):
    ratings_tmp.write_text(json.dumps({"equipos": {llave: {
        "nombre": "Viejo", "pais": None, "liga": None,
        "rating": rating, "rd": rd, "vol": 0.06,
        "partidos_jugados": jugados, "partidos_bootstrap": 0,
        "partidos_reales": jugados, "ultima_actualizacion": "2025-01-01",
    }}}), encoding="utf-8")


def test_registro_nuevo_con_semilla_arranca_en_1750(ratings_tmp):
    eq = ratings_store.obtener_o_crear("espn:101", nombre="Sembrado FC",
                                       elo_semilla=1750.0)
    assert eq["rating"] == 1750.0
    assert eq["rd"] == ratings_store.RD_SEMILLA_CLUBELO


def test_registro_nuevo_sin_semilla_arranca_en_1500(ratings_tmp):
    eq = ratings_store.obtener_o_crear("espn:102", nombre="Normal FC")
    assert eq["rating"] == ratings_store.glicko2.RATING_BASE
    assert eq["rd"] == ratings_store.glicko2.RD_INICIAL


def test_registro_vacio_antiguo_se_resiembra(ratings_tmp):
    _registro_vacio(ratings_tmp, "espn:103")
    eq = ratings_store.obtener_o_crear("espn:103", elo_semilla=1750.0)
    assert eq["rating"] == 1750.0
    assert eq["rd"] == ratings_store.RD_SEMILLA_CLUBELO


def test_resiembra_solo_una_vez(ratings_tmp):
    _registro_vacio(ratings_tmp, "espn:104")
    ratings_store.obtener_o_crear("espn:104", elo_semilla=1750.0)
    eq = ratings_store.obtener_o_crear("espn:104", elo_semilla=1799.0)
    assert eq["rating"] == 1750.0  # la segunda llamada no vuelve a sembrar


def test_registro_con_partidos_no_se_resiembra(ratings_tmp):
    _registro_vacio(ratings_tmp, "espn:105", rating=1500.0, rd=350.0,
                    jugados=3)
    eq = ratings_store.obtener_o_crear("espn:105", elo_semilla=1750.0)
    assert eq["rating"] == 1500.0
    assert eq["rd"] == 350.0


def test_registro_vacio_con_rating_distinto_no_se_resiembra(ratings_tmp):
    _registro_vacio(ratings_tmp, "espn:106", rating=1610.0, rd=150.0)
    eq = ratings_store.obtener_o_crear("espn:106", elo_semilla=1750.0)
    assert eq["rating"] == 1610.0


def test_rating_combinado_pasa_su_elo_como_semilla(ratings_tmp):
    ratings_store.rating_combinado("espn:107", 1750.0, nombre="Desde Blend")
    datos = json.loads(ratings_tmp.read_text(encoding="utf-8"))
    eq = datos["equipos"]["espn:107"]
    assert eq["rating"] == 1750.0
    assert eq["rd"] == ratings_store.RD_SEMILLA_CLUBELO

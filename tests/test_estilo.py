"""Estilo de juego (Tarea 3): columnas reales del CSV de football-data,
emparejamiento de nombres por similitud y cache en memoria por liga."""
import csv
from pathlib import Path

import pytest

import resumen as R
from fetch_data import temporada_anterior, temporada_actual

RUTA_CSV = Path(__file__).parent / "fixtures" / "football_data_e0_sample.csv"


@pytest.fixture
def filas():
    with open(RUTA_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def entorno(monkeypatch, filas):
    """Mock de obtener_resultados_liga: la temporada anterior viene vacia
    (evita duplicar el fixture) y la actual con las filas del fixture.
    Registra (codigo, temporada) de cada descarga."""
    llamadas = []

    def _mock(codigo, temporada=None):
        llamadas.append((codigo, temporada))
        if temporada == temporada_anterior():
            return []
        return filas

    monkeypatch.setattr(R, "obtener_resultados_liga", _mock)
    monkeypatch.setattr(R, "_CSV_LIGA", {})
    return llamadas


def test_man_united_empareja_con_manchester_united(entorno):
    datos = R._obtener_datos_estilo("Man United", "eng.1")
    assert datos is not None
    assert len(datos) == 6  # 8 filas validas, se quedan con las ultimas 6
    # primera fila valida conservada: Man United 3-0 Everton (de casa)
    assert datos[0]["tiros_totales"] == 16.0
    assert datos[0]["goles_1t"] == 2.0  # HTHG, no FTHG//2
    # segunda: Liverpool 1-2 Man United (de visitante usa columnas AS/...)
    assert datos[1]["tiros_totales"] == 13.0
    assert datos[1]["goles_1t"] == 1.0  # HTAG
    assert all(isinstance(d["corners"], float) for d in datos)


def test_equipo_desconocido_devuelve_none(entorno):
    assert R._obtener_datos_estilo("Equipo Inexistente XYZ", "eng.1") is None


def test_liga_sin_mapeo_devuelve_none(entorno):
    # col.1 no tiene cobertura en football-data.co.uk
    assert R._obtener_datos_estilo("Man United", "col.1") is None
    assert entorno == []  # ni una descarga: la liga no esta en el mapa


def test_se_descarga_una_vez_por_liga_y_temporada(entorno):
    R._obtener_datos_estilo("Man United", "eng.1")
    R._obtener_datos_estilo("Leeds", "eng.1")
    R._obtener_datos_estilo("Man United", "eng.1")
    # solo una pareja de descargas (anterior + actual) para toda la liga
    assert entorno == [
        ("E0", temporada_anterior()),
        ("E0", temporada_actual()),
    ]
    assert "E0" in R._CSV_LIGA


def test_fila_sin_marcador_final_no_cuenta(entorno):
    """La fila de Man United vs Fulham sin FTHG/FTAG queda fuera."""
    filas_fulham = [f for f in R._obtener_datos_estilo("Man United", "eng.1")
                    if f["tiros_totales"] == 11.0]
    # la unica fila con 11 tiros de Man United de casa es la invalida
    # (Everton tiene 16 y Leeds 14): no debe aparecer
    assert filas_fulham == []


def test_ligas_nuevas_en_el_mapa():
    # verificadas en vivo contra football-data (2526 y 2627, stats completas)
    assert R.MAPA_LIGA_SLUG_A_CODIGO["eng.3"] == "E2"
    assert R.MAPA_LIGA_SLUG_A_CODIGO["eng.4"] == "E3"
    assert R.MAPA_LIGA_SLUG_A_CODIGO["por.2"] == "P2"
    assert R.MAPA_LIGA_SLUG_A_CODIGO["sco.2"] == "SC1"
    assert R.MAPA_LIGA_SLUG_A_CODIGO["sco.3"] == "SC2"
    # sin stats completas en football-data: quedan fuera del mapa
    for slug in ("usa.1", "arg.1", "bra.1", "mex.1",
                 "ger.3", "ned.2", "bel.2", "tur.2", "eng.5"):
        assert slug not in R.MAPA_LIGA_SLUG_A_CODIGO


def test_alias_resuelve_nombres_de_espn():
    nombres = ["Man City", "Man United", "Leeds", "Sp Lisbon", "FC Porto"]
    # nombre largo de ESPN -> abreviado de football-data
    assert R._emparejar_nombre("Manchester City", nombres) == "Man City"
    assert R._emparejar_nombre("Leeds United", nombres) == "Leeds"
    # caso clasico que el difflib 0.72 no resuelve
    assert R._emparejar_nombre("Sporting CP", nombres) == "Sp Lisbon"
    # el nombre exacto gana sobre el alias
    assert R._emparejar_nombre("Man City", nombres) == "Man City"


def test_alias_a_un_nombre_ausente_cae_a_difflib():
    nombres = ["FC Porto", "Braga"]
    # el alias existe pero "Sp Lisbon" no esta en esta liga: sin match claro
    assert R._emparejar_nombre("Sporting CP", nombres) is None


def test_alias_cubierto_en_el_mapa():
    # cada alias debe apuntar a un nombre usado por football-data en
    # al menos una temporada; el caso "Deportivo" solo esta en SP1 2627
    assert R.ALIAS_NOMBRES_FOOTBALL_DATA["Deportivo"] == "La Coruna"
    assert R.ALIAS_NOMBRES_FOOTBALL_DATA["Partick Thistle"] == "Partick"
    assert len(R.ALIAS_NOMBRES_FOOTBALL_DATA) >= 35

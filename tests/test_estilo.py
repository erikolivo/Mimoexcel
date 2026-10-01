"""Estilo de juego (Tarea 3): columnas reales del CSV de football-data,
emparejamiento de nombres por similitud y cache en memoria por liga."""
import csv
from pathlib import Path

import pytest

import resumen as R

RUTA_CSV = Path(__file__).parent / "fixtures" / "football_data_e0_sample.csv"


@pytest.fixture
def filas():
    with open(RUTA_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def entorno(monkeypatch, filas):
    """Mock de obtener_resultados_liga que cuenta las descargas."""
    llamadas = []

    def _mock(codigo, temporada=None):
        llamadas.append(codigo)
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
    assert R._obtener_datos_estilo("Man United", "brasil.1") is None
    assert entorno == []  # ni una descarga: la liga no esta en el mapa


def test_se_descarga_una_vez_por_liga(entorno):
    R._obtener_datos_estilo("Man United", "eng.1")
    R._obtener_datos_estilo("Leeds", "eng.1")
    R._obtener_datos_estilo("Man United", "eng.1")
    assert entorno == ["E0"]
    assert "E0" in R._CSV_LIGA


def test_fila_sin_marcador_final_no_cuenta(entorno):
    """La fila de Man United vs Fulham sin FTHG/FTAG queda fuera."""
    filas_fulham = [f for f in R._obtener_datos_estilo("Man United", "eng.1")
                    if f["tiros_totales"] == 11.0]
    # la unica fila con 11 tiros de Man United de casa es la invalida
    # (Everton tiene 16 y Leeds 14): no debe aparecer
    assert filas_fulham == []

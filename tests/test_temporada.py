"""Temporada dinamica de football-data y respaldo de la anterior.

Sin red y sin escribir en data/.
"""

import datetime

import fetch_data as F


def test_temporada_actual_en_curso():
    assert F.temporada_actual(datetime.date(2026, 10, 24)) == "2627"


def test_temporada_actual_en_mitad_de_temporada():
    assert F.temporada_actual(datetime.date(2026, 3, 1)) == "2526"


def test_temporada_actual_justo_al_inicio():
    assert F.temporada_actual(datetime.date(2026, 7, 15)) == "2627"
    assert F.temporada_actual(datetime.date(2027, 1, 2)) == "2627"


def test_temporada_actual_nunca_lanza():
    assert F.temporada_actual("no es una fecha") == F.temporada_actual()
    assert len(F.temporada_actual()) == 4


def test_temporada_anterior():
    assert F._temporada_anterior("2627") == "2526"
    assert F._temporada_anterior("2526") == "2425"
    assert F._temporada_anterior("xx") is None


def test_respaldo_si_la_temporada_en_curso_esta_vacia(monkeypatch):
    monkeypatch.setattr(F, "temporada_actual", lambda hoy=None: "2627")
    llamadas = []

    def falso(codigo, temporada):
        llamadas.append(temporada)
        return [] if temporada == "2627" else [{"fila": i} for i in range(F.MIN_PARTIDOS_TEMPORADA)]

    monkeypatch.setattr(F, "_descargar_resultados_temporada", falso)
    resultados = F.obtener_resultados_liga("E0")
    assert len(resultados) == F.MIN_PARTIDOS_TEMPORADA
    assert llamadas == ["2627", "2526"]


def test_respaldo_si_la_temporada_en_curso_tiene_pocos_partidos(monkeypatch):
    monkeypatch.setattr(F, "temporada_actual", lambda hoy=None: "2627")

    def falso(codigo, temporada):
        return [{"fila": 1}] if temporada == "2627" else [{"fila": i} for i in range(100)]

    monkeypatch.setattr(F, "_descargar_resultados_temporada", falso)
    assert len(F.obtener_resultados_liga("E0")) == 100


def test_sin_respaldo_cuando_la_temporada_esta_completa(monkeypatch):
    monkeypatch.setattr(F, "temporada_actual", lambda hoy=None: "2627")
    llamadas = []

    def falso(codigo, temporada):
        llamadas.append(temporada)
        return [{"fila": i} for i in range(F.MIN_PARTIDOS_TEMPORADA)]

    monkeypatch.setattr(F, "_descargar_resultados_temporada", falso)
    assert len(F.obtener_resultados_liga("E0")) == F.MIN_PARTIDOS_TEMPORADA
    assert llamadas == ["2627"]


def test_temporada_historica_explicita_no_usa_respaldo(monkeypatch):
    # bootstrap pide ["2425", "2526"] a proposito: no debe duplicar datos
    # cayendo a la temporada anterior.
    monkeypatch.setattr(F, "temporada_actual", lambda hoy=None: "2627")
    llamadas = []

    def falso(codigo, temporada):
        llamadas.append(temporada)
        return [{"fila": 1}]

    monkeypatch.setattr(F, "_descargar_resultados_temporada", falso)
    assert F.obtener_resultados_liga("E0", "2425") == [{"fila": 1}]
    assert llamadas == ["2425"]


def test_sin_datos_de_nada_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setattr(F, "temporada_actual", lambda hoy=None: "2627")
    monkeypatch.setattr(F, "_descargar_resultados_temporada", lambda codigo, temporada: None)
    assert F.obtener_resultados_liga("E0") == []

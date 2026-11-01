"""Datos de elo-tilt por equipo: Elo, forma y overperformance.

Sin red: las respuestas HTTP se simulan. Nunca escribe en data/.
"""

import datetime

import pytest

import datos_elo as D

HOY = datetime.date(2026, 10, 31)


@pytest.fixture(autouse=True)
def _limpiar_cache():
    D._cache.update({"fecha": None, "cargado": None, "por_fixture": {}, "por_nombres": {}})
    yield
    D._cache.update({"fecha": None, "cargado": None, "por_fixture": {}, "por_nombres": {}})


def _pred(fixture="401877564", local="Mito Hollyhock", visitante="Sanfrecce Hiroshima"):
    return {
        "fixture_id": fixture,
        "equipo_local": {
            "nombre": local, "rating": 1312.31, "form_score": 0.3,
            "ultimos5": {"texto": "5D"}, "overperformance": -7.0, "momentum": "stable",
        },
        "equipo_visitante": {
            "nombre": visitante, "rating": 1603.03, "form_score": 76.3,
            "ultimos5": {"texto": "3V 2D"}, "overperformance": 6.2, "momentum": "up",
        },
    }


class _Respuesta:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_indexar_por_fixture_y_por_nombres():
    por_fixture, por_nombres = D._indexar([_pred()])
    assert "401877564" in por_fixture
    assert por_nombres[("mito hollyhock", "sanfrecce hiroshima")]["fixture_id"] == "401877564"


def test_resumen_equipo_solo_campos_utiles():
    resumen = D._resumen_equipo(_pred()["equipo_local"])
    assert resumen["rating"] == 1312.31
    assert resumen["forma"] == "5D"
    assert resumen["form_score"] == 0.3
    assert resumen["overperformance"] == -7.0
    assert D._resumen_equipo({}) is None
    assert D._resumen_equipo(None) is None


def test_datos_de_partido_por_fixture_y_por_nombres(monkeypatch):
    por_fixture, por_nombres = D._indexar([_pred()])
    monkeypatch.setattr(D, "obtener_datos", lambda *a, **k: (por_fixture, por_nombres))
    monkeypatch.setattr(D.historial_elo, "rating_de", lambda team_id: None)

    por_id = D.datos_de_partido({"fixture_id": "401877564", "local": "X", "visitante": "Y"})
    assert por_id["local"]["rating"] == 1312.31

    # Sin fixture_id: se busca por nombres, ignorando acentos/mayusculas.
    por_nombre = D.datos_de_partido({"fixture_id": "", "local": "MITO HOLLYHOCK", "visitante": "Sanfrecce Hiroshima"})
    assert por_nombre["visitante"]["forma"] == "3V 2D"

    assert D.datos_de_partido({"local": "A", "visitante": "B"}) is None


def test_completa_elo_desde_ratings_si_no_hay_prediccion(monkeypatch):
    monkeypatch.setattr(D, "obtener_datos", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(D.historial_elo, "rating_de", lambda team_id: {"rating": 1500.0, "rd": 100.0})
    datos = D.datos_de_partido({"home_id": 10, "away_id": 20, "local": "A", "visitante": "B"})
    assert datos["local"]["rating"] == 1500.0
    assert datos["visitante"]["rating"] == 1500.0
    # Sin forma ni overperformance: solo hay Elo.
    assert datos["local"]["forma"] is None


def test_lineas_elo_formato(monkeypatch):
    por_fixture, por_nombres = D._indexar([_pred(local="Cambrian & Clydach")])
    monkeypatch.setattr(D, "obtener_datos", lambda *a, **k: (por_fixture, por_nombres))
    monkeypatch.setattr(D.historial_elo, "rating_de", lambda team_id: None)

    lineas = D.lineas_elo({
        "fixture_id": "401877564", "local": "Cambrian & Clydach", "visitante": "Sanfrecce Hiroshima",
    })
    assert lineas[0] == "📐 Elo y forma (elo-tilt):"
    assert lineas[1] == "  Cambrian &amp; Clydach: Elo 1312 | forma 5D · 0 | overperf -7.0"
    assert lineas[2] == "  Sanfrecce Hiroshima: Elo 1603 | forma 3V 2D · 76 | overperf +6.2"


def test_lineas_elo_sin_datos_es_vacio(monkeypatch):
    monkeypatch.setattr(D, "obtener_datos", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(D.historial_elo, "rating_de", lambda team_id: None)
    assert D.lineas_elo({"local": "A", "visitante": "B"}) == []


def test_lineas_elo_nunca_lanza(monkeypatch):
    def roto(*args, **kwargs):
        raise RuntimeError("sin red")

    monkeypatch.setattr(D, "obtener_datos", roto)
    assert D.lineas_elo({"local": "A", "visitante": "B"}) == []


def test_obtener_datos_usa_archivo_del_dia(monkeypatch):
    urls = []

    def fake_get(url, timeout=None, **kwargs):
        urls.append(url)
        if "predicciones_2026-10-31.json" in url:
            return _Respuesta(404)
        return _Respuesta(200, {"fecha_consulta": "2026-10-31", "predicciones": [_pred()]})

    monkeypatch.setattr(D.requests, "get", fake_get)
    por_fixture, _ = D.obtener_datos(HOY)
    assert "401877564" in por_fixture
    assert urls[0].endswith("predicciones_2026-10-31.json")
    assert urls[1].endswith("predicciones_cache.json")

    # Segunda llamada: usa la cache en memoria, sin otra peticion.
    D.obtener_datos(HOY)
    assert len(urls) == 2

    # forzar=True vuelve a descargar.
    D.obtener_datos(HOY, forzar=True)
    assert len(urls) == 4


def test_obtener_datos_descarta_cache_de_otro_dia(monkeypatch):
    def fake_get(url, timeout=None, **kwargs):
        return _Respuesta(200, {"fecha_consulta": "2026-10-30", "predicciones": [_pred()]})

    monkeypatch.setattr(D.requests, "get", fake_get)
    por_fixture, por_nombres = D.obtener_datos(HOY)
    assert por_fixture == {} and por_nombres == {}


def test_obtener_datos_sobrevive_a_errores_de_red(monkeypatch):
    import requests as requests_lib

    def fake_get(url, timeout=None, **kwargs):
        raise requests_lib.ConnectionError("sin red")

    monkeypatch.setattr(D.requests, "get", fake_get)
    assert D.obtener_datos(HOY) == ({}, {})

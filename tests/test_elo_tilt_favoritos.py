"""Tests del respaldo de favoritos elo-tilt (solo lectura de su JSON).

No toca data/ y no hace red: las respuestas HTTP se mockean.
"""

import json
from datetime import date

import elo_tilt_favoritos as E
import seleccionar_partidos as S

HOY = date(2026, 10, 4)


def _pred(p_local, p_empate, p_visitante, local="Alpha FC", visitante="Beta United",
          fid=1001, conf=50.0):
    return {
        "fecha": "2026-10-04", "fecha_display": "domingo, 4 oct", "hora": "15:00",
        "liga": "Premier League", "liga_slug": "eng.1",
        "equipo_local": {"nombre": local, "id": 10},
        "equipo_visitante": {"nombre": visitante, "id": 20},
        "prediccion": {"prob_local": p_local, "prob_empate": p_empate, "prob_visitante": p_visitante},
        "confianza": conf, "fixture_id": fid,
    }


def _datos(preds, fecha="2026-10-04"):
    return {"fecha_consulta": fecha, "total": len(preds), "predicciones": preds}


def test_directo_local_y_visitante():
    datos = _datos([_pred(70, 20, 10), _pred(10, 20, 70, fid=1002)])
    entradas = E.interpretar_predicciones(datos, HOY)
    assert [e["favorito"] for e in entradas] == ["LOCAL", "VISITANTE"]
    assert entradas[0]["fixture_id"] == "1001"
    assert entradas[0]["fila_hoja"] == "1001"
    assert entradas[0]["prioridad"] == "MEDIA"      # conf=50
    assert entradas[0]["confianza_estrellas"] == 2


def test_banda_dc_y_descarte_bajo_45():
    datos = _datos([
        _pred(50, 30, 20),                          # 50% -> DC LOCAL
        _pred(46, 30, 24, fid=1002),                # 46% -> DC VISITANTE? no: lado 46 local
        _pred(44, 30, 26, fid=1003),                # 44% -> se descarta
    ])
    entradas = E.interpretar_predicciones(datos, HOY)
    assert [e["favorito"] for e in entradas] == ["DC LOCAL", "DC LOCAL"]


def test_prioridad_por_confianza():
    datos = _datos([
        _pred(70, 20, 10, fid=1, conf=80),   # ALTA
        _pred(70, 20, 10, fid=2, conf=40),   # MEDIA
        _pred(70, 20, 10, fid=3, conf=10),   # BAJA
    ])
    entradas = E.interpretar_predicciones(datos, HOY)
    assert [e["prioridad"] for e in entradas] == ["ALTA", "MEDIA", "BAJA"]
    assert [e["confianza_estrellas"] for e in entradas] == [3, 2, 1]


def test_cache_de_otro_dia_se_descarta():
    datos = _datos([_pred(70, 20, 10)], fecha="2026-10-03")
    assert E.interpretar_predicciones(datos, HOY) == []


def test_nombres_se_limpian():
    datos = _datos([_pred(70, 20, 10, local="  Alpha FC ", visitante="Beta  United")])
    entradas = E.interpretar_predicciones(datos, HOY)
    assert entradas[0]["local"] == "Alpha FC"
    assert entradas[0]["visitante"] == "Beta  United"


class _Respuesta:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_descarga_prueba_dia_y_luego_cache(monkeypatch):
    llamadas = []

    def fake_get(url, timeout=None, **kwargs):
        llamadas.append(url)
        if "predicciones_2026-10-04.json" in url:
            return _Respuesta(404, None)
        return _Respuesta(200, _datos([_pred(70, 20, 10)]))

    monkeypatch.setattr(E.requests, "get", fake_get)
    entradas = E.obtener_favoritos_elo_tilt(hoy=HOY)
    assert len(entradas) == 1
    assert llamadas == [E.URL_POR_FECHA.format(fecha="2026-10-04"), E.URL_CACHE]


def test_cache_viejo_devuelve_vacio(monkeypatch):
    def fake_get(url, timeout=None, **kwargs):
        return _Respuesta(200, _datos([_pred(70, 20, 10)], fecha="2026-10-03"))

    monkeypatch.setattr(E.requests, "get", fake_get)
    assert E.obtener_favoritos_elo_tilt(hoy=HOY) == []


def test_error_de_red_devuelve_vacio(monkeypatch):
    import requests as requests_lib

    def fake_get(url, timeout=None, **kwargs):
        raise requests_lib.ConnectionError("sin red")

    monkeypatch.setattr(E.requests, "get", fake_get)
    assert E.obtener_favoritos_elo_tilt(hoy=HOY) == []


def _fixture_espn(fid=777, local="Alpha FC", visitante="Beta United"):
    return {
        "fixture": {"id": fid, "date": "2026-10-04T20:00:00+00:00"},
        "teams": {"home": {"name": local, "id": 1}, "away": {"name": visitante, "id": 2}},
        "league": {"country": "England", "name": "Premier League"},
        "_liga_slug": "eng.1",
    }


def test_busca_fixture_por_id_sin_fuzzy():
    fixtures = [_fixture_espn(fid=777)]
    entrada = {"local": "Nombre Que No Coincide", "visitante": "Otro Nombre", "fixture_id": "777"}
    assert S._buscar_fixture_por_id(entrada, fixtures) is fixtures[0]
    assert S._buscar_fixture_por_id({"local": "x", "visitante": "y"}, fixtures) is None
    assert S._buscar_fixture_por_id({"local": "x", "visitante": "y", "fixture_id": ""}, fixtures) is None


def test_partido_para_vigilar_con_fuente_elo_tilt():
    partido = S._partido_para_vigilar(
        _fixture_espn(), "DC LOCAL", "777", 2, prioridad="MEDIA", fuente="elo-tilt")
    assert partido["fuente_favorito"] == "elo-tilt"
    assert partido["tipo_pronostico"] == "doble_oportunidad"
    assert partido["favorito_es_local"] is True
    assert partido["favorito"] == "Alpha FC"
    assert partido["prioridad"] == "MEDIA"
    assert partido["fila_fuente"] == "777"


def test_partido_para_vigilar_default_sigue_siendo_google_sheets():
    partido = S._partido_para_vigilar(_fixture_espn(), "LOCAL", "12")
    assert partido["fuente_favorito"] == "Google Sheets"
    assert partido["tipo_pronostico"] == "favorito_directo"


def _entrada_elo():
    return {
        "local": "Alpha FC", "visitante": "Beta United", "favorito": "LOCAL",
        "fila_hoja": "777", "fixture_id": "777",
        "confianza_texto": "**", "confianza_estrellas": 2,
        "cuota_local": None, "cuota_empate": None, "cuota_visitante": None,
        "prioridad": "ALTA",
    }


def test_ya_se_completo_acepta_partidos_elo_tilt(monkeypatch, tmp_path):
    archivo = tmp_path / "partidos_hoy.json"
    archivo.write_text(json.dumps({
        "fecha": "2026-10-04", "seleccion_version": S.VERSION_SELECCION,
        "partidos": [{"fuente_favorito": "elo-tilt"}],
    }), encoding="utf-8")
    monkeypatch.setattr(S, "ARCHIVO_SALIDA", archivo)
    monkeypatch.setattr(S, "fecha_local_hoy", lambda: "2026-10-04")
    assert S.ya_se_completo_hoy() is True
    archivo.write_text(json.dumps({
        "fecha": "2026-10-04", "seleccion_version": S.VERSION_SELECCION,
        "partidos": [{"fuente_favorito": "fuente_desconocida"}],
    }), encoding="utf-8")
    assert S.ya_se_completo_hoy() is False


def test_seleccionar_usa_elo_tilt_si_hoja_falla(monkeypatch, tmp_path):
    archivo = tmp_path / "partidos_hoy.json"

    def hoja_falla(**kwargs):
        raise RuntimeError("hoja caida")

    def elo_ok(**kwargs):
        return [_entrada_elo()]

    monkeypatch.setattr(S, "ARCHIVO_SALIDA", archivo)
    monkeypatch.setattr(S, "fecha_local_hoy", lambda: "2026-10-04")
    monkeypatch.setattr(S, "obtener_favoritos_google", hoja_falla)
    monkeypatch.setattr(S, "obtener_favoritos_elo_tilt", elo_ok)
    monkeypatch.setattr(S, "obtener_fixtures_por_fecha", lambda hoy: [_fixture_espn()])

    S.seleccionar()
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert datos["fecha"] == "2026-10-04"
    assert len(datos["partidos"]) == 1
    partido = datos["partidos"][0]
    assert partido["fuente_favorito"] == "elo-tilt"
    assert partido["fixture_id"] == 777
    assert partido["favorito"] == "Alpha FC"


def test_seleccionar_con_hoja_no_llama_elo_tilt(monkeypatch, tmp_path):
    archivo = tmp_path / "partidos_hoy.json"
    llamado = {"elo": False}

    def elo_no_deberia_llamarse(**kwargs):
        llamado["elo"] = True
        return [_entrada_elo()]

    def hoja_ok(**kwargs):
        entrada = _entrada_elo()
        entrada.pop("fixture_id")
        return [entrada]

    monkeypatch.setattr(S, "ARCHIVO_SALIDA", archivo)
    monkeypatch.setattr(S, "fecha_local_hoy", lambda: "2026-10-04")
    monkeypatch.setattr(S, "obtener_favoritos_google", hoja_ok)
    monkeypatch.setattr(S, "obtener_favoritos_elo_tilt", elo_no_deberia_llamarse)
    monkeypatch.setattr(S, "obtener_fixtures_por_fecha", lambda hoy: [_fixture_espn()])

    S.seleccionar()
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert llamado["elo"] is False
    assert datos["partidos"][0]["fuente_favorito"] == "Google Sheets"

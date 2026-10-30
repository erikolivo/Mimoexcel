"""Historial desde elo-tilt: filtros, tope de meses y cache.

Sin red y sin escribir en data/ (CACHE_FILE se redirige a tmp_path).
"""

import datetime
import json

import historial_elo as H

HOY = datetime.date(2026, 10, 28)


def _partido(fixture_id, local_id, visitante_id, gl, gv, fecha="2026-10-01",
             liga="esp.1", nombre=None):
    return {
        "fixture_id": str(fixture_id), "fecha": fecha,
        "liga_slug": liga, "liga_nombre": nombre if nombre is not None else liga,
        "equipo_local": {"id": str(local_id), "name": "Local"},
        "equipo_visitante": {"id": str(visitante_id), "name": "Visitante"},
        "goles_local": gl, "goles_visitante": gv,
    }


def _preparar(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "CACHE_FILE", str(tmp_path / "cache_historial_elo.json"))
    monkeypatch.setattr(H, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(H, "_ahora", lambda: datetime.datetime(2026, 10, 28, 12, 0))
    H._cache_memoria.clear()
    H._cache_meses.clear()


def test_meses_a_consultar():
    assert H._meses_a_consultar(HOY) == ["2026-10", "2026-09", "2026-08"]
    assert H._meses_a_consultar(datetime.date(2027, 1, 5)) == ["2027-01", "2026-12", "2026-11"]


def test_partidos_del_equipo_filtra_y_ordena():
    datos = {"partidos": [
        _partido(3, 86, 90, 2, 1, fecha="2026-10-20"),
        _partido(1, 91, 86, 0, 3, fecha="2026-10-01"),          # visitante, gana
        _partido(2, 86, 92, 1, 1, fecha="2026-10-10"),          # empate
        _partido(4, 86, 93, None, 1, fecha="2026-10-15"),       # sin marcador
        _partido(5, 86, 94, 4, 0, fecha="2026-10-18", liga="club.friendly"),  # amistoso
        _partido(1, 91, 86, 0, 3, fecha="2026-10-01"),          # duplicado
    ]}
    historial = H._partidos_del_equipo(datos, "86")
    assert [p["id"] for p in historial] == ["1", "2", "3"]
    assert [p["resultado"] for p in historial] == ["V", "E", "V"]
    assert historial[0]["es_local"] is False and historial[0]["goles_favor"] == 3
    assert historial[0]["rival_id"] == "91"
    assert historial[0]["competicion"] == "esp.1"


def test_amistoso_por_nombre_y_liga():
    datos = {"partidos": [_partido(1, 86, 90, 1, 0, liga="all", nombre="Club Friendly")]}
    assert H._partidos_del_equipo(datos, "86") == []


def test_obtener_historial_para_al_juntar_8(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    pedidos = []

    def falso(mes):
        pedidos.append(mes)
        base = {"2026-10": 5, "2026-09": 4, "2026-08": 30}[mes]
        return {"partidos": [
            _partido(f"{mes}-{i}", 86, 90 + i, 1, 0, fecha=f"{mes}-{i + 1:02d}")
            for i in range(base)
        ]}

    monkeypatch.setattr(H, "_descargar_mes", falso)
    historial = H.obtener_historial_equipo_elo("86", hoy=HOY)
    assert len(historial) == 9
    assert pedidos == ["2026-10", "2026-09"]   # se detuvo al pasar de 8
    assert [p["fecha"] for p in historial] == sorted(p["fecha"] for p in historial)


def test_mes_no_publicado_404_da_lista_vacia(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_descargar_mes", lambda mes: [])
    assert H.obtener_historial_equipo_elo("86", hoy=HOY) == []


def test_cache_en_disco_evita_segunda_descarga(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    descargas = []

    def falso(mes):
        descargas.append(mes)
        return {"partidos": [_partido("1", 86, 90, 2, 0, fecha="2026-10-20")]}

    monkeypatch.setattr(H, "_descargar_mes", falso)
    assert len(H.obtener_historial_equipo_elo("86", hoy=HOY)) == 1
    primeras = list(descargas)

    H._cache_memoria.clear()   # fuerza a leer el cache de disco
    assert len(H.obtener_historial_equipo_elo("86", hoy=HOY)) == 1
    assert descargas == primeras


def test_cache_vencido_vuelve_a_descargar(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    (tmp_path / "cache_historial_elo.json").write_text(json.dumps({
        "86|2026-10": {"fecha_cache": "2026-10-28T00:00:00",   # 12 h > 3 h
                       "historial": [{"id": "viejo", "fecha": "2026-10-01"}]},
    }), encoding="utf-8")
    descargas = []

    def falso(mes):
        descargas.append(mes)
        return {"partidos": [_partido("nuevo", 86, 90, 1, 0, fecha="2026-10-20")]}

    monkeypatch.setattr(H, "_descargar_mes", falso)
    historial = H.obtener_historial_equipo_elo("86", hoy=HOY)
    assert [p["id"] for p in historial] == ["nuevo"]
    assert descargas[0] == "2026-10"   # el mes vencido SI se vuelve a descargar
    assert len(descargas) == 3         # sigue buscando hasta 3 meses (< 8 partidos)


def test_nunca_lanza_con_entradas_raras(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(H, "_descargar_mes", lambda mes: {"partidos": [None, "x", {}]})
    assert H.obtener_historial_equipo_elo(None) == []
    assert H.obtener_historial_equipo_elo("", hoy=HOY) == []
    assert H.obtener_historial_equipo_elo("86", hoy=HOY) == []


# ── rating_de (ajuste por rival) ──────────────────────────────────────────

def _limpiar_ratings():
    H._cache_ratings["equipos"] = {}
    H._cache_ratings["cargado_en"] = None


def test_rating_de_lee_el_mapa_de_elo_tilt(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    _limpiar_ratings()
    monkeypatch.setattr(H, "_cargar_ratings",
                        lambda: {"espn:86": {"rating": 1600, "rd": 80.0}})
    assert H.rating_de("86") == {"rating": 1600.0, "rd": 80.0}
    assert H.rating_de(86) == {"rating": 1600.0, "rd": 80.0}
    assert H.rating_de("desconocido") is None
    assert H.rating_de(None) is None


def test_rating_de_datos_invalidos(monkeypatch):
    _limpiar_ratings()
    monkeypatch.setattr(H, "_cargar_ratings",
                        lambda: {"espn:86": {"rating": None}, "espn:87": "x"})
    assert H.rating_de("86") is None
    assert H.rating_de("87") is None


def test_ratings_caen_al_archivo_local(monkeypatch, tmp_path):
    _limpiar_ratings()
    monkeypatch.setattr(H, "RATINGS_LOCAL_FILE", str(tmp_path / "ratings_propios.json"))
    monkeypatch.setattr(H, "_descargar_json", lambda url, etiqueta: ("error", None))
    (tmp_path / "ratings_propios.json").write_text(json.dumps({
        "equipos": {"espn:86": {"rating": 1700, "rd": 90}},
    }), encoding="utf-8")
    assert H.rating_de("86") == {"rating": 1700.0, "rd": 90.0}
    _limpiar_ratings()


def test_ratings_se_cachean(monkeypatch):
    _limpiar_ratings()
    llamadas = []

    def descarga(url, etiqueta):
        llamadas.append(url)
        return "ok", {"equipos": {"espn:86": {"rating": 1600, "rd": 80}}}

    monkeypatch.setattr(H, "_descargar_json", descarga)
    assert H.rating_de("86")["rating"] == 1600
    assert H.rating_de("86")["rating"] == 1600
    assert len(llamadas) == 1
    _limpiar_ratings()


def test_sin_ratings_no_lanza(monkeypatch, tmp_path):
    _limpiar_ratings()
    monkeypatch.setattr(H, "RATINGS_LOCAL_FILE", str(tmp_path / "no_existe.json"))
    monkeypatch.setattr(H, "_descargar_json", lambda url, etiqueta: ("error", None))
    assert H.rating_de("86") is None
    _limpiar_ratings()


def test_archivo_mensual_se_descarga_una_vez_por_proceso(monkeypatch):
    H._cache_meses.clear()
    llamadas = []

    def descarga(url, etiqueta):
        llamadas.append(url)
        return "ok", {"partidos": [{"fixture_id": "1"}]}

    monkeypatch.setattr(H, "_descargar_json", descarga)
    assert H._descargar_mes("2026-10") == {"partidos": [{"fixture_id": "1"}]}
    assert H._descargar_mes("2026-10") == {"partidos": [{"fixture_id": "1"}]}
    assert len(llamadas) == 1
    H._cache_meses.clear()

"""Tarea 4: el Nivel Actual se registra en el partido y en cada alerta
(sin cambiar el mensaje visible ni el Excel)."""
import monitor


def _partido(**extra):
    base = {"fixture_id": 77, "favorito_es_local": True,
            "local": "Alpha FC", "visitante": "Beta FC",
            "favorito": "Alpha FC", "no_favorito": "Beta FC",
            "tipo_pronostico": "favorito_directo",
            "alertas_enviadas": []}
    base.update(extra)
    return base


def _snap():
    return {"stats_local": {}, "stats_visitante": {},
            "goles_local": 1, "goles_visitante": 0}


def test_mensaje_partido_guarda_nivel_redondeado(monkeypatch):
    historial = [{"id": str(i), "fecha": f"2026-01-{i + 1:02d}", "resultado": "V",
                  "goles_favor": 3, "goles_contra": 0, "es_local": True}
                 for i in range(6)]
    monkeypatch.setattr(monitor, "obtener_historial_equipo",
                        lambda tid, slug: historial)
    partido = _partido(home_id=1, away_id=2, liga_slug="eng.1")
    monitor._mensaje_partido(partido, "10'", _snap(), "Alerta de prueba")
    assert partido["nivel_local"] == 10.0
    assert partido["nivel_visitante"] == 10.0
    assert isinstance(partido["nivel_local"], float)


def test_mensaje_partido_sin_datos_deja_none(monkeypatch):
    monkeypatch.setattr(monitor, "obtener_historial_equipo",
                        lambda tid, slug: [])
    partido = _partido(home_id=1, away_id=2, liga_slug="eng.1")
    monitor._mensaje_partido(partido, "10'", _snap(), "Alerta de prueba")
    assert partido["nivel_local"] is None
    assert partido["nivel_visitante"] is None

    sin_ids = _partido()
    monitor._mensaje_partido(sin_ids, "10'", _snap(), "Alerta de prueba")
    assert sin_ids["nivel_local"] is None
    assert sin_ids["nivel_visitante"] is None


def test_alerta_registrada_copia_el_nivel_del_partido():
    partido = _partido(nivel_local=6.7, nivel_visitante=None)
    monitor._registrar_alerta(partido, "gol_de_cierre", "Texto", "78'",
                              marcador=[1, 0])
    alerta = partido["alertas_enviadas"][-1]
    assert alerta["nivel_local"] == 6.7
    assert alerta["nivel_visitante"] is None


def test_alerta_sin_nivel_calculado_guarda_none():
    partido = _partido()  # sin nivel_local/nivel_visitante en el dict
    monitor._registrar_alerta(partido, "gol_de_cierre", "Texto", "78'")
    alerta = partido["alertas_enviadas"][-1]
    assert alerta["nivel_local"] is None
    assert alerta["nivel_visitante"] is None

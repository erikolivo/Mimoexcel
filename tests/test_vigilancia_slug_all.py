"""Vigilancia de partidos con liga_slug 'all'.

Los fixtures hallados solo en el scoreboard global (los que trae
elo-tilt) traen liga_slug 'all'. El monitor los saltaba en vivo
(solo aviso final) -> cero snapshots y cero alertas. Ahora usan el
mismo camino que el resto, via /all/summary?event= de ESPN.

No escribe fuera de tmp_path (el heartbeat tambien se redirige)."""

import datetime
import json

import monitor as m


def _partido(fid=999, minutos=30):
    kickoff = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(minutes=minutos)).isoformat()
    return {
        "partido": "Alpha vs Beta", "local": "Alpha", "visitante": "Beta",
        "favorito": "Alpha", "no_favorito": "Beta", "favorito_es_local": True,
        "tipo_pronostico": "favorito_directo", "confianza_estrellas": 2,
        "cuota_local_inicial": None, "cuota_empate_inicial": None,
        "cuota_visitante_inicial": None,
        "prioridad": "ALTA", "fuente_favorito": "elo-tilt", "fila_fuente": str(fid),
        "hora_inicio": kickoff, "fixture_id": fid, "liga_slug": "all",
        "liga_pais": "", "liga_nombre": "", "home_id": 1, "away_id": 2,
        "kickoff_utc": kickoff, "resultado_final": None, "acierto": None,
        "historial_snapshots": [], "alertas_enviadas": [],
        "diferencia_maxima_alcanzada": 0,
    }


def _box(estado="in", minuto="12'"):
    return {"estado": estado, "minuto": minuto, "periodo": "1H",
            "estado_detalle": None, "goles_local": 0, "goles_visitante": 0,
            "stats_local": {"totalShots": "3"}, "stats_visitante": {"totalShots": "1"}}


def _preparar(monkeypatch, tmp_path, partido, box):
    archivo = tmp_path / "partidos_hoy.json"
    archivo.write_text(json.dumps({"fecha": "2026-10-05", "partidos": [partido]}),
                       encoding="utf-8")
    llamadas = []

    def fake_box(slug, fid):
        llamadas.append((slug, fid))
        return box

    monkeypatch.setattr(m, "ARCHIVO_PARTIDOS", archivo)
    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "obtener_boxscore_en_vivo", fake_box)
    monkeypatch.setattr(m, "enviar_mensaje_telegram", lambda *a, **k: True)
    return archivo, llamadas


def test_slug_all_recibe_snapshot_en_vivo(monkeypatch, tmp_path):
    archivo, llamadas = _preparar(monkeypatch, tmp_path, _partido(), _box())
    m.vigilar()
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert llamadas == [("all", 999)]
    assert len(datos["partidos"][0]["historial_snapshots"]) == 1
    assert datos["partidos"][0]["historial_snapshots"][0]["minuto"] == "12'"


def test_slug_all_finalizado_marca_aviso(monkeypatch, tmp_path):
    archivo, llamadas = _preparar(monkeypatch, tmp_path, _partido(),
                                   _box(estado="post", minuto=None))
    m.vigilar()
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert llamadas == [("all", 999)]
    assert datos["partidos"][0]["aviso_final_enviado"] is True
    assert datos["partidos"][0]["historial_snapshots"] == []


def test_slug_vacio_se_trata_como_all(monkeypatch, tmp_path):
    partido = _partido()
    partido["liga_slug"] = ""
    archivo, llamadas = _preparar(monkeypatch, tmp_path, partido, _box())
    m.vigilar()
    assert llamadas == [("all", 999)]

"""Historial de ESPN: solo partidos terminados, deduplicado y ordenado.

Usa tests/fixtures/espn_schedule_sample.json (respuesta real recortada)
y respuestas armadas para los casos borde. Sin red ni escrituras en data/.
"""

import json
from pathlib import Path

import fetch_data as F

FIXTURE = Path(__file__).parent / "fixtures" / "espn_schedule_sample.json"


def _respuesta(eventos):
    class Respuesta:
        status_code = 200

        @staticmethod
        def json():
            return {"events": eventos}

    return Respuesta()


def _evento(evento_id, fecha, gf, gv, team_id="86", rival_id="90",
            completado=True, es_local=True, con_estado=True):
    competitors = [
        {"id": team_id, "homeAway": "home" if es_local else "away",
         "score": None if gf is None else {"value": gf}},
        {"id": rival_id, "homeAway": "away" if es_local else "home",
         "score": None if gv is None else {"value": gv}},
    ]
    comp = {"date": fecha, "competitors": competitors}
    if con_estado:
        comp["status"] = {"type": {"completed": completado,
                                   "state": "post" if completado else "pre"}}
    return {"id": evento_id, "date": fecha,
            "league": {"slug": "esp.1", "name": "Spanish LALIGA"},
            "competitions": [comp]}


def _sin_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "CACHE_HISTORIAL_FILE", str(tmp_path / "cache_historial_v2.json"))
    monkeypatch.setattr(F, "DATA_DIR", str(tmp_path))


def test_fixture_real_se_parsea_completo(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _respuesta(data["events"]))
    historial = F._obtener_historial_todas_competiciones("86")
    assert len(historial) == 6
    assert [p["fecha"] for p in historial] == sorted(p["fecha"] for p in historial)
    assert all(p["rival_id"] for p in historial)
    assert all(p["competicion"] for p in historial)
    assert "esp.1" in {p["competicion"] for p in historial}   # liga + copas
    assert {p["resultado"] for p in historial} <= {"V", "E", "D"}


def test_partido_no_terminado_no_cuenta(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    eventos = [
        _evento("1", "2026-10-20T19:00Z", 2, 0, completado=True),
        _evento("2", "2026-10-21T19:00Z", 1, 1, completado=False),   # futuro/en curso
        _evento("3", "2026-10-22T19:00Z", 3, 0, completado=None),    # sin estado, futuro
    ]
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _respuesta(eventos))
    historial = F._obtener_historial_todas_competiciones("86")
    assert [p["id"] for p in historial] == ["1"]


def test_sin_marcador_no_se_inventa_cero(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    eventos = [
        _evento("1", "2026-10-20T19:00Z", None, None),             # sin marcador
        _evento("2", "2026-10-21T19:00Z", 2, None),                # falta el rival
        _evento("3", "2026-10-22T19:00Z", 1, 0),                   # valido
        _evento("4", "2020-01-01T19:00Z", 1, 0, con_estado=False),  # viejo sin estado
    ]
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _respuesta(eventos))
    historial = F._obtener_historial_todas_competiciones("86")
    assert [p["id"] for p in historial] == ["4", "3"]   # orden ascendente


def test_deduplica_por_id_de_evento(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    eventos = [_evento("1", "2026-10-20T19:00Z", 2, 0),
               _evento("1", "2026-10-20T19:00Z", 2, 0)]
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _respuesta(eventos))
    assert len(F._obtener_historial_todas_competiciones("86")) == 1


def test_es_local_y_rival_se_leen_del_competidor(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    eventos = [_evento("1", "2026-10-20T19:00Z", 2, 0, es_local=False, rival_id="77")]
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _respuesta(eventos))
    partido = F._obtener_historial_todas_competiciones("86")[0]
    assert partido["es_local"] is False
    assert partido["rival_id"] == "77"
    assert (partido["goles_favor"], partido["goles_contra"], partido["resultado"]) == (2, 0, "V")


def test_cache_viejo_no_se_reutiliza(monkeypatch, tmp_path):
    _sin_cache(monkeypatch, tmp_path)
    # El cache v2 (clave vieja) no debe leerse: se consulta ESPN de nuevo.
    (tmp_path / "cache_historial_v2.json").write_text(json.dumps({
        "86_all_2010": {"fecha_cache": "2026-10-28T00:00:00",
                        "historial": [{"id": "viejo", "fecha": "2010-01-01"}]},
    }), encoding="utf-8")
    llamadas = []

    def falso(url, **kwargs):
        llamadas.append(url)
        return _respuesta([_evento("nuevo", "2026-10-20T19:00Z", 1, 0)])

    monkeypatch.setattr(F.requests, "get", falso)
    historial = F._obtener_historial_todas_competiciones("86")
    assert [p["id"] for p in historial] == ["nuevo"]
    assert llamadas and all("/all/teams/86/schedule?season=" in url for url in llamadas)


def test_selector_usa_elo_si_hay_suficientes(monkeypatch):
    monkeypatch.setattr(F, "obtener_historial_equipo_elo", lambda team_id: [{"id": i} for i in range(4)])
    monkeypatch.setattr(F, "_historial_espn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamar a ESPN")))
    assert len(F.obtener_historial_equipo("86", "esp.1")) == 4


def test_selector_cae_a_espn_si_falta_historial(monkeypatch):
    monkeypatch.setattr(F, "obtener_historial_equipo_elo", lambda team_id: [{"id": 1}] * 3)
    monkeypatch.setattr(F, "_historial_espn", lambda team_id, slug, anio=None: [{"id": "espn"}])
    assert F.obtener_historial_equipo("86", "esp.1") == [{"id": "espn"}]

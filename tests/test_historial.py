"""Historial de equipo confiable (Tarea 1): solo partidos terminados,
temporadas [año-1, año], cache v2 de 12 horas y parseo unificado."""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import fetch_data as F

RUTA_FIXTURE = Path(__file__).parent / "fixtures" / "espn_schedule_sample.json"

# Equipo del fixture: Atletico-MG (5 terminados + 1 futuro con equipo presente)
EQUIPO = 7632
# Equipo del partido en curso (col.1): solo el estado lo salva
EQUIPO_EN_CURSO = 5264


@pytest.fixture
def muestra():
    return json.loads(RUTA_FIXTURE.read_text(encoding="utf-8"))


def _ids(historial):
    return {p["id"] for p in historial}


def test_futuros_no_aparecen(muestra):
    """El partido pre con el equipo presente (401841168) y el otro pre no cuentan."""
    historial = F._parsear_eventos(muestra, EQUIPO)
    assert "401841168" not in _ids(historial)
    assert "761798" not in _ids(historial)
    assert len(historial) == 5


def test_en_curso_no_aparece(muestra):
    """El partido state=in (401877865) tiene al equipo, pero no esta terminado."""
    historial = F._parsear_eventos(muestra, EQUIPO_EN_CURSO)
    assert "401877865" not in _ids(historial)


def test_futuro_sin_marcador_no_aparece(muestra):
    """Sin estado y con fecha futura: se descarta en vez de inventar un 0-0."""
    datos = copy.deepcopy(muestra)
    evento = next(e for e in datos["events"] if e["id"] == "401841168")
    evento["date"] = "2099-01-01T12:00:00Z"
    evento.pop("status", None)
    comp = evento["competitions"][0]
    comp["date"] = "2099-01-01T12:00:00Z"
    comp.pop("status", None)
    for c in comp["competitors"]:
        c.pop("score", None)
    historial = F._parsear_eventos(datos, EQUIPO)
    assert "401841168" not in _ids(historial)


def test_terminado_sin_marcador_no_inventa_cero_cero(muestra):
    """Terminado pero sin score de uno de los dos: se descarta, no da 0-0."""
    datos = copy.deepcopy(muestra)
    evento = next(e for e in datos["events"] if e["id"] == "401841231")
    for c in evento["competitions"][0]["competitors"]:
        c.pop("score", None)
    historial = F._parsear_eventos(datos, EQUIPO)
    assert "401841231" not in _ids(historial)


def test_resultados_y_sede(muestra):
    historial = F._parsear_eventos(muestra, EQUIPO)
    assert len(historial) == 5
    for p in historial:
        if p["resultado"] == "V":
            assert p["goles_favor"] > p["goles_contra"]
        elif p["resultado"] == "D":
            assert p["goles_favor"] < p["goles_contra"]
        else:
            assert p["goles_favor"] == p["goles_contra"]
    por_id = {p["id"]: p for p in historial}
    assert por_id["401841231"]["resultado"] == "V" and por_id["401841231"]["es_local"] is True
    assert por_id["401841226"]["resultado"] == "D" and por_id["401841226"]["es_local"] is False
    assert por_id["401841164"]["resultado"] == "V" and por_id["401841164"]["es_local"] is False
    assert por_id["401841204"]["resultado"] == "E" and por_id["401841204"]["es_local"] is False
    assert por_id["401841239"]["resultado"] == "E" and por_id["401841239"]["es_local"] is True


def test_orden_ascendente_sin_duplicados(muestra):
    """Entrada invertida y duplicada: sale ordenada y sin ids repetidos."""
    datos = {"events": list(reversed(muestra["events"])) * 2}
    historial = F._parsear_eventos(datos, EQUIPO)
    fechas = [p["fecha"] for p in historial]
    assert fechas == sorted(fechas)
    assert len(_ids(historial)) == len(historial) == 5


def test_amistoso_no_cuenta():
    """Los amistosos se marcan en event.league (comp.type no existe en ESPN)."""
    evento = {"id": "99999999",
              "league": {"slug": "club.friendly", "name": "Club Friendly"},
              "competitions": [{
                  "date": "2026-01-10T12:00:00Z",
                  "status": {"type": {"completed": True, "state": "post"}},
                  "competitors": [
                      {"id": str(EQUIPO), "homeAway": "home",
                       "score": {"value": 2.0, "displayValue": "2"}},
                      {"id": "111111", "homeAway": "away",
                       "score": {"value": 0.0, "displayValue": "0"}},
                  ]}]}
    assert F._es_amistoso(evento) is True
    assert F._parsear_eventos({"events": [evento]}, EQUIPO) == []


class _Respuesta:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data


def test_cache_v2_no_reutiliza_el_viejo(muestra, tmp_path, monkeypatch):
    """La clave nueva v2|... ignora el cache viejo; la segunda llamada si cachea."""
    archivo = tmp_path / "cache_historial.json"
    viejo = {"7632_bra.1_2026": {
        "fecha_cache": datetime.now().isoformat(),
        "historial": [{"fecha": "1999-01-01", "goles_favor": 9, "goles_contra": 0,
                       "es_local": True, "resultado": "V"}],
    }}
    archivo.write_text(json.dumps(viejo), encoding="utf-8")

    llamadas = []

    def _get(url, timeout=None, **kwargs):
        llamadas.append(url)
        return _Respuesta(muestra)

    monkeypatch.setattr(F, "CACHE_HISTORIAL_FILE", str(archivo))
    monkeypatch.setattr(F.requests, "get", _get)

    historial = F.obtener_historial_equipo(EQUIPO, "bra.1")
    assert len(llamadas) == 2  # una peticion por temporada: año-1 y año
    assert all("schedule?season=" in u for u in llamadas)
    assert all("/bra.1/teams/7632/schedule" in u for u in llamadas)
    # la clave vieja esta fresca pero no se reutiliza: vienen datos nuevos
    assert len(historial) == 5  # misma respuesta en ambas temporadas: dedupe
    assert all(p["fecha"] != "1999-01-01" for p in historial)
    cache = json.loads(archivo.read_text(encoding="utf-8"))
    assert "7632_bra.1_2026" in cache and "v2|7632|bra.1" in cache

    llamadas.clear()
    historial2 = F.obtener_historial_equipo(EQUIPO, "bra.1")
    assert llamadas == []  # cache v2 vigente (12 h): sin nuevas peticiones
    assert historial2 == historial

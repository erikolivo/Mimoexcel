"""Temporada de football-data: autodeteccion de la temporada vigente
(antes hardcodeada en 2526) y descarga robusta sin temporada."""
import datetime

import fetch_data as F


def _fecha(anio, mes, dia):
    return datetime.datetime(anio, mes, dia, tzinfo=datetime.timezone.utc)


def test_arrancan_en_agosto():
    assert F.temporada_actual(_fecha(2026, 9, 30)) == "2627"
    assert F.temporada_actual(_fecha(2026, 12, 1)) == "2627"
    assert F.temporada_actual(_fecha(2026, 8, 1)) == "2627"


def test_de_enero_a_julio_sigue_la_misma():
    assert F.temporada_actual(_fecha(2027, 1, 15)) == "2627"
    assert F.temporada_actual(_fecha(2027, 7, 31)) == "2627"
    assert F.temporada_actual(_fecha(2026, 7, 31)) == "2526"
    assert F.temporada_actual(_fecha(2026, 1, 2)) == "2526"


def test_temporada_anterior():
    assert F.temporada_anterior(_fecha(2026, 9, 30)) == "2526"
    assert F.temporada_anterior(_fecha(2027, 7, 31)) == "2526"
    assert F.temporada_anterior(_fecha(2027, 8, 1)) == "2627"


def test_descarga_sin_temporada_usa_la_vigente(monkeypatch):
    llamadas = []

    class _Resp:
        status_code = 200
        text = "Date,HomeTeam,AwayTeam\n01/08/2026,A,B\n"

        def raise_for_status(self):
            pass

    def _get(url, timeout=None):
        llamadas.append(url)
        return _Resp()

    monkeypatch.setattr(F.requests, "get", _get)
    filas = F.obtener_resultados_liga("E0")
    assert llamadas and f"/{F.temporada_actual()}/E0.csv" in llamadas[0]
    assert filas and filas[0]["HomeTeam"] == "A"


def test_respuesta_300_da_vacio(monkeypatch):
    """Archivo inexistente: football-data responde 300 con HTML de
    sugerencias (no es 404, raise_for_status no lo atrapa)."""
    class _Resp:
        status_code = 300
        text = "<html>Multiple Choices</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(F.requests, "get", lambda url, timeout=None: _Resp())
    assert F.obtener_resultados_liga("E0", "9999") == []

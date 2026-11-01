"""Observabilidad: nivel/color del partido guardado en cada alerta.

Antes el Nivel Actual se calculaba solo para el texto del mensaje y se
perdia; ahora queda en la alerta para poder segmentar el acierto en el
informe semanal. Sin red y sin escribir en data/.
"""

import monitor as M

PARTIDO = {
    "fixture_id": 999,
    "local": "Alpha FC",
    "visitante": "Beta United",
    "favorito_es_local": True,
    "home_id": 10,
    "away_id": 20,
    "liga_slug": "eng.1",
    "historial_snapshots": [],
    "alertas_enviadas": [],
    "nivel_actual": {
        "local": {"poder": 8.4, "color": "🔵", "n": 6},
        "visitante": {"poder": 3.1, "color": "🔴", "n": 6},
    },
}


def test_registrar_alerta_guarda_nivel_y_color():
    partido = {**PARTIDO, "alertas_enviadas": []}
    M._registrar_alerta(partido, "gol_favorito", "Gol", "30")
    alerta = partido["alertas_enviadas"][0]
    assert alerta["nivel_local"] == 8.4
    assert alerta["nivel_visitante"] == 3.1
    assert alerta["color_local"] == "🔵"
    assert alerta["color_visitante"] == "🔴"


def test_registrar_alerta_sin_nivel_deja_none_pero_registra():
    partido = {"fixture_id": 1, "local": "A", "visitante": "B",
               "alertas_enviadas": [], "nivel_actual": {"local": None, "visitante": None}}
    M._registrar_alerta(partido, "gol_favorito", "Gol", "30")
    alerta = partido["alertas_enviadas"][0]
    assert alerta["nivel_local"] is None
    assert alerta["color_visitante"] is None
    assert alerta["tipo"] == "gol_favorito"


def test_nivel_del_partido_calcula_y_cachea(monkeypatch):
    llamadas = []

    def historial(team_id, liga_slug):
        llamadas.append((team_id, liga_slug))
        return [{"goles_favor": 1}]

    def nivel(historial_equipo, es_local, team_id=None):
        return (7.5 if es_local else 5.5), ("🟢" if es_local else "🟡"), 6

    monkeypatch.setattr(M, "obtener_historial_equipo", historial)
    monkeypatch.setattr(M, "_calcular_nivel_actual", nivel)

    partido = {"home_id": 10, "away_id": 20, "liga_slug": "eng.1"}
    contexto = M._nivel_del_partido(partido)
    assert contexto["local"]["poder"] == 7.5
    assert contexto["visitante"]["color"] == "🟡"
    assert partido["nivel_actual"] == contexto
    assert len(llamadas) == 2

    # La segunda vez usa el cache: no vuelve a consultar historial.
    M._nivel_del_partido(partido)
    assert len(llamadas) == 2


def test_nivel_del_partido_nunca_lanza(monkeypatch):
    def historial_roto(*args, **kwargs):
        raise RuntimeError("sin datos")

    monkeypatch.setattr(M, "obtener_historial_equipo", historial_roto)
    partido = {"home_id": 10, "away_id": 20, "liga_slug": "eng.1"}
    assert M._nivel_del_partido(partido) == {"local": None, "visitante": None}


def test_nivel_del_partido_sin_ids_no_consulta(monkeypatch):
    def no_deberia_llamarse(*args, **kwargs):
        raise AssertionError("no deberia consultar historial")

    monkeypatch.setattr(M, "obtener_historial_equipo", no_deberia_llamarse)
    assert M._nivel_del_partido({"local": "A"}) == {"local": None, "visitante": None}

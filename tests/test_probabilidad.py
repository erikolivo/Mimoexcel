"""Parche de probabilidad: lectura de % de la hoja, calibracion y filtro.

Sin red y sin escribir en data/.
"""

import datetime

import google_favoritos as G
import probabilidad as P
import seleccionar_partidos as S

HOY = datetime.date(2026, 10, 28)

CSV_CON_PCT = """Pais,Liga,Fecha,Hora (Ecuador),Local,% Local,Cuota 1,Cuota X,Cuota 2,% Visitante,Visitante,Pronostico,Confianza,Prioridad,Fixture ID
Spain,La Liga,28/10/2026,20:00,Real Madrid,80%,1.25,6.00,11.00,9%,Real Sociedad,LOCAL,★★★,BAJA,1570340
Spain,La Liga,28/10/2026,21:00,Girona,43%,2.35,3.40,2.62,38%,Sevilla,LOCAL,★,ALTA,1570341
Spain,La Liga,28/10/2026,22:00,Getafe,25%,4.00,4.00,1.62,62%,Betis,VISITANTE,★★,ALTA,1570342
Spain,La Liga,28/10/2026,23:00,Osasuna,55%,1.83,3.50,3.75,27%,Valencia,DC LOCAL,★★★,MEDIA,1570343
"""


def test_interpretar_csv_lee_pct_local_y_visitante():
    favs = G.interpretar_csv(CSV_CON_PCT, hoy=HOY)
    assert len(favs) == 4
    assert favs[0]["pct_local"] == 0.80
    assert favs[0]["pct_visitante"] == 0.09
    assert favs[2]["pct_local"] == 0.25
    assert favs[2]["pct_visitante"] == 0.62


def test_columna_pct_no_confunde_con_el_nombre_del_equipo():
    encabezados = ["% Local", "Local", "% Visitante", "Visitante"]
    assert G._columna_pct(encabezados, "local") == "% Local"
    assert G._columna_pct(encabezados, "visitante") == "% Visitante"
    assert G._columna_pct(["Local", "Visitante"], "local") is None


def test_sin_columnas_de_pct_queda_none_y_no_filtra():
    csv_viejo = "Fecha,Local,Visitante,Pronostico\n28/10/2026,A,B,LOCAL\n"
    favoritos = G.interpretar_csv(csv_viejo, hoy=HOY)
    assert favoritos[0]["pct_local"] is None
    assert favoritos[0]["pct_visitante"] is None
    assert P.evaluar(favoritos[0]["pct_local"], favoritos[0]["pct_visitante"], "local") is None


def test_a_fraccion_formatos():
    assert P.a_fraccion("80%") == 0.8
    assert P.a_fraccion("0.80") == 0.8
    assert P.a_fraccion("0,65") == 0.65
    assert P.a_fraccion(80) == 0.8
    assert P.a_fraccion(None) is None
    assert P.a_fraccion("n/a") is None
    assert P.a_fraccion("150%") is None


def test_prioridad_desde_pf_umbrales():
    assert P.prioridad_desde_pf(0.75) == "ALTA"
    assert P.prioridad_desde_pf(0.74) == "MEDIA"
    assert P.prioridad_desde_pf(0.65) == "MEDIA"
    assert P.prioridad_desde_pf(0.649) == "BAJA"


def test_evaluar_favorito_local_y_visitante():
    local = P.evaluar("0.80", "0.09", "local")
    assert local["pf_hoja"] == 0.8 and local["seguir"] is True
    assert local["prioridad"] == "ALTA"
    assert 0 <= local["p_gana_fav"] <= 1 and local["p_no_pierde_fav"] >= local["p_gana_fav"]

    visitante = P.evaluar("0.25", "0.62", "visitante")
    assert visitante["pf_hoja"] == 0.62
    assert visitante["prioridad"] == "BAJA"
    assert visitante["seguir"] is False  # 0.62 < PF_MIN_SEGUIMIENTO


def test_evaluar_sin_datos_o_lado_invalido_devuelve_none():
    assert P.evaluar(None, "0.3", "local") is None
    assert P.evaluar("0.3", None, "local") is None
    assert P.evaluar("0.3", "0.2", None) is None
    assert P.evaluar("0.3", "0.2", "empate") is None


def test_tramos_ordenados_y_seguir_usa_el_minimo():
    ganancias = [t[2] for t in P.TRAMOS]
    assert ganancias == sorted(ganancias)
    justo = P.evaluar(str(P.PF_MIN_SEGUIMIENTO), "0.10", "local")
    assert justo["seguir"] is True
    debajo = P.evaluar(str(P.PF_MIN_SEGUIMIENTO - 0.01), "0.10", "local")
    assert debajo["seguir"] is False


FIXTURE = {
    "fixture": {"id": 1570340, "date": "2026-10-28T20:00:00Z"},
    "teams": {"home": {"id": "86", "name": "Real Madrid"},
              "away": {"id": "89", "name": "Real Sociedad"}},
    "league": {"country": "Spain", "name": "La Liga"},
    "_liga_slug": "esp.1",
}


def test_partido_para_vigilar_guarda_prioridad_recalculada_y_probabilidad():
    info_prob = P.evaluar("0.80", "0.09", "local")
    partido = S._partido_para_vigilar(
        FIXTURE, "LOCAL", 2, 3, prioridad=info_prob["prioridad"],
        info_prob=info_prob, prioridad_hoja="BAJA",
    )
    assert partido["prioridad"] == "ALTA"        # recalculada
    assert partido["prioridad_hoja"] == "BAJA"   # la de la hoja, para auditar
    assert partido["p_gana_fav"] == info_prob["p_gana_fav"]
    assert partido["p_no_pierde_fav"] == info_prob["p_no_pierde_fav"]


def test_partido_para_vigilar_sin_pct_deja_probabilidad_none():
    partido = S._partido_para_vigilar(
        FIXTURE, "LOCAL", 2, 3, prioridad="ALTA", info_prob=None, prioridad_hoja="ALTA",
    )
    assert partido["p_gana_fav"] is None
    assert partido["p_no_pierde_fav"] is None
    assert partido["prioridad"] == "ALTA"

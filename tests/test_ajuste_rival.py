"""Ajuste del Nivel Actual por la calidad del rival (ratings de elo-tilt).

Sin red y sin escribir en data/: rating_de se reemplaza por una tabla.
"""

import resumen as R


RATINGS = {
    "yo": {"rating": 1500.0, "rd": 80.0},
    "fuerte": {"rating": 1900.0, "rd": 80.0},
    "debil": {"rating": 1250.0, "rd": 80.0},
    "medio": {"rating": 1600.0, "rd": 80.0},
    "impreciso": {"rating": 1900.0, "rd": 400.0},
}


def _instalar(monkeypatch):
    monkeypatch.setattr(R, "AJUSTE_RIVAL_ACTIVO", True)
    monkeypatch.setattr(R, "rating_de", lambda team_id: RATINGS.get(str(team_id)))


def _p(resultado, rival="fuerte", es_local=False):
    return {"fecha": "2026-10-01", "resultado": resultado, "goles_favor": 1,
            "goles_contra": 0, "es_local": es_local, "rival_id": rival}


def test_sin_team_id_o_sin_rival_no_cambia(monkeypatch):
    _instalar(monkeypatch)
    assert R._valor_resultado({"resultado": "V"}) == 1.0
    assert R._valor_resultado({"resultado": "D"}) == 0.0
    assert R._valor_resultado(_p("V"), "yo") == 1.0   # rival fuerte: tope 1.0


def test_ganar_a_un_rival_flojo_vale_menos(monkeypatch):
    _instalar(monkeypatch)
    # local: 1500 + 50 = 1550 vs 1250 -> -300, tope -250 -> -0.3125
    assert R._valor_resultado(_p("V", rival="debil", es_local=True), "yo") == 0.6875
    # visitante: 1500 - 50 = 1450 vs 1250 -> -200 -> -0.25
    assert R._valor_resultado(_p("V", rival="debil", es_local=False), "yo") == 0.75


def test_perder_contra_un_rival_fuerte_duele_menos(monkeypatch):
    _instalar(monkeypatch)
    assert R._valor_resultado(_p("D", rival="fuerte", es_local=False), "yo") == 0.3125
    # perder contra uno flojo sigue en 0
    assert R._valor_resultado(_p("D", rival="debil", es_local=True), "yo") == 0.0


def test_empate_se_ajusta_en_ambos_sentidos(monkeypatch):
    _instalar(monkeypatch)
    assert R._valor_resultado(_p("E", rival="fuerte"), "yo") == 0.8125
    assert R._valor_resultado(_p("E", rival="debil", es_local=True), "yo") == 0.1875


def test_rd_alto_o_rating_ausente_no_ajusta(monkeypatch):
    _instalar(monkeypatch)
    assert R._valor_resultado(_p("D", rival="impreciso"), "yo") == 0.0
    assert R._valor_resultado(_p("D", rival="desconocido"), "yo") == 0.0
    assert R._valor_resultado(_p("D"), "sin_rating") == 0.0


def test_ajuste_apagado_es_el_comportamiento_viejo(monkeypatch):
    _instalar(monkeypatch)
    monkeypatch.setattr(R, "AJUSTE_RIVAL_ACTIVO", False)
    for resultado in ("V", "E", "D"):
        assert R._valor_resultado(_p(resultado), "yo") == {
            "V": 1.0, "E": 0.5, "D": 0.0}[resultado]


def test_ventaja_de_local_suaviza_el_ajuste(monkeypatch):
    _instalar(monkeypatch)
    # misma derrota contra un rival algo mejor: de local duele menos
    local = R._valor_resultado(_p("D", rival="medio", es_local=True), "yo")
    visitante = R._valor_resultado(_p("D", rival="medio", es_local=False), "yo")
    assert local < visitante
    assert local == 0.0625 and visitante == 0.1875


def test_nivel_actual_usa_el_ajuste(monkeypatch):
    _instalar(monkeypatch)
    derrotas_fuertes = [_p("D", rival="fuerte", es_local=True) for _ in range(4)]
    victorias_flojas = [dict(_p("V", rival="debil", es_local=True), goles_favor=3,
                             goles_contra=0) for _ in range(4)]

    con_ajuste = R._calcular_nivel_actual(derrotas_fuertes, True, "yo")[0]
    sin_ajuste = R._calcular_nivel_actual(derrotas_fuertes, True)[0]
    assert con_ajuste > sin_ajuste   # perder contra fuertes no es tan malo

    con_ajuste = R._calcular_nivel_actual(victorias_flojas, True, "yo")[0]
    sin_ajuste = R._calcular_nivel_actual(victorias_flojas, True)[0]
    assert con_ajuste < sin_ajuste   # ganar a flojos no vale lo mismo


def test_sin_rival_id_el_nivel_no_cambia(monkeypatch):
    _instalar(monkeypatch)
    historial = [{"fecha": f"2026-01-0{i}", "resultado": "V", "goles_favor": 1,
                  "goles_contra": 0, "es_local": True} for i in range(1, 5)]
    assert R._calcular_nivel_actual(historial, True, "yo") == R._calcular_nivel_actual(historial, True)

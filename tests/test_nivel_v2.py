"""Nivel v2 — Commit 1: orden defensivo del historial y pesos.

Reglas del README (seccion 2):
- El resultado NO depende del orden en que llega el historial.
- El partido mas reciente pesa 1.0 (0.85 hacia atras): una victoria
  reciente pesa mas que una victoria vieja.
Sin escrituras en data/ y sin red.
"""

import resumen as R


def _p(fecha, resultado, gf, gc, es_local=True):
    return {"fecha": fecha, "resultado": resultado, "goles_favor": gf,
            "goles_contra": gc, "es_local": es_local}


def _asc():
    # 4 partidos: derrotas viejas, victoria reciente
    return [_p("2026-01-01", "D", 0, 0), _p("2026-01-10", "D", 0, 0),
            _p("2026-01-20", "D", 0, 0), _p("2026-01-30", "V", 1, 0)]


def test_mismo_resultado_en_orden_asc_y_desc():
    asc = _asc()
    desc = list(reversed(asc))
    assert R._calcular_nivel_actual(asc, True) == R._calcular_nivel_actual(desc, True)
    assert R._calcular_nivel_actual(asc, False) == R._calcular_nivel_actual(desc, False)


def test_victoria_reciente_pesa_mas_que_vieja():
    # Mismo balance para ambos: 3 derrotas 0-0 y una victoria 1-0.
    # A: derrotas viejas + victoria RECIENTE
    a = _asc()
    # B: victoria vieja + derrotas RECIENTES  -> debe ser menor
    b = [_p("2026-01-01", "V", 1, 0), _p("2026-01-10", "D", 0, 0),
         _p("2026-01-20", "D", 0, 0), _p("2026-01-30", "D", 0, 0)]
    poder_a, _, _ = R._calcular_nivel_actual(a, True)
    poder_b, _, _ = R._calcular_nivel_actual(b, True)
    assert poder_a is not None and poder_b is not None
    assert poder_a > poder_b, f"esperaba A>B: {poder_a} vs {poder_b}"


def test_ordenar_historial_ascendente():
    desc = [_p("2026-03-01", "V", 1, 0), _p("2026-02-01", "E", 1, 1),
            _p("2026-01-01", "D", 0, 2)]
    asc = R.ordenar_historial(desc)
    assert [p["fecha"] for p in asc] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    # nunca lanza excepcion
    assert R.ordenar_historial(None) == []
    assert R.ordenar_historial([{"sin_fecha": 1}]) == [{"sin_fecha": 1}]


def test_pocos_partidos_sigue_devolviendo_none():
    assert R._calcular_nivel_actual([], True) == (None, None, 0)
    assert R._calcular_nivel_actual(_asc()[:3], True) == (None, None, 0)
    # incluso llegando en orden descendente
    assert R._calcular_nivel_actual(list(reversed(_asc()))[:3], True) == (None, None, 0)


# ── Commit 2: escala de goles, sede con tope y minimo, firma team_id ──────

def test_score_goles_15_dif_da_80():
    # +1.5 goles de diferencia por partido -> 50 + 1.5*20 = 80
    ultimos = [_p("2026-02-01", "V", 1, 0), _p("2026-02-05", "V", 2, 0),
               _p("2026-02-10", "V", 1, 0), _p("2026-02-15", "V", 2, 0)]
    # diferencias por partido: +1, +2, +1, +2 -> promedio +1.5
    assert R._score_goles_global(ultimos) == 80.0


def test_score_goles_tope_0_100():
    goleada = [_p("2026-02-01", "V", 9, 0)] * 4
    paliza = [_p("2026-02-01", "D", 0, 9)] * 4
    assert R._score_goles_global(goleada) == 100.0
    assert R._score_goles_global(paliza) == 0.0


def test_sede_con_1_partido_se_mezcla_con_forma_global():
    hist = [_p("2026-01-01", "E", 1, 1, es_local=False), _p("2026-01-05", "E", 1, 1, es_local=False),
            _p("2026-01-10", "E", 1, 1, es_local=False), _p("2026-01-15", "E", 1, 1, es_local=False),
            _p("2026-01-20", "V", 1, 0)]  # unico de local = el ultimo
    forma_global = 100 * (0.5 * (0.85 ** 4 + 0.85 ** 3 + 0.85 ** 2 + 0.85) + 1.0) / sum(
        0.85 ** i for i in range(5))
    sede = R._score_sede(hist, True, forma_global)
    # ns=1 -> w=1/3: 1/3 * crudo + 2/3 * forma_global ; crudo = 50+(1-0.5)*60+8 = 88
    crudo = 50 + (1 - 0.5) * 60 + (1 - 0) * 8
    assert abs(sede - (crudo / 3 + forma_global * 2 / 3)) < 1e-9


def test_sede_con_2_partidos_pesa_2_3_y_respeta_0_100():
    hist = [_p("2026-01-01", "V", 9, 0), _p("2026-01-05", "V", 9, 0),
            _p("2026-01-10", "D", 0, 4, es_local=False)]
    forma_global = 20.0
    sede = R._score_sede(hist, True, forma_global)
    assert 0 <= sede <= 100
    # ns=2 -> w=2/3 ; crudo con tope 100 (9-0 da 50+30+72 -> 100)
    assert abs(sede - (100 * 2 / 3 + forma_global / 3)) < 1e-9


def test_sede_sin_partidos_en_esa_sede_usa_forma_global():
    hist = [_p("2026-01-01", "V", 5, 0, es_local=False)]
    assert R._score_sede(hist, True, 42.0) == 42.0


def test_poder_siempre_entre_0_y_10():
    for h in ([_p("2026-01-01", "V", 9, 0)] * 6, [_p("2026-01-01", "D", 0, 9)] * 6,
              [_p("2026-01-01", "E", 0, 0)] * 6):
        poder, color, n = R._calcular_nivel_actual(h, True)
        assert 0 <= poder <= 10 and n == 6 and color


def test_firma_vieja_y_nueva_conviven():
    h = _asc()
    assert R._calcular_nivel_actual(h, True) == R._calcular_nivel_actual(h, True, "123")
    assert R._calcular_nivel_actual(h, True, "123")[0] is not None


def test_mezcla_liga_y_copa_se_ventanea_por_fecha():
    # 8 partidos alternando competicion; la etiqueta no debe influir.
    liga_copa = []
    for i in range(8):
        comp = "liga" if i % 2 == 0 else "copa"
        liga_copa.append(dict(_p(f"2026-03-{i + 1:02d}", "V" if i % 3 else "D", 1 + i % 2, i % 2),
                              competicion=comp))
    solo_fechas = sorted(liga_copa, key=lambda p: p["fecha"])
    assert R._calcular_nivel_actual(liga_copa, True) == R._calcular_nivel_actual(solo_fechas, True)
    # y la ventana son los 6 mas recientes por fecha
    assert [p["fecha"] for p in solo_fechas[-6:]][-1] == "2026-03-08"

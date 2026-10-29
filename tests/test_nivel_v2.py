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

"""Nivel Actual (Tarea 2): pesos de recencia correctos, componentes en
misma escala 0-100 y defensa contra historiales desordenados."""
import random

from resumen import (_calcular_nivel_actual, _pesos_recencia,
                     _forma_0_100, _goles_0_100)


def _p(i, resultado, gf, gc, es_local=True):
    return {"id": str(1000 + i), "fecha": f"2026-01-{i + 1:02d}",
            "resultado": resultado, "goles_favor": gf, "goles_contra": gc,
            "es_local": es_local}


def _victorias(n=6):
    return [_p(i, "V", 3, 0) for i in range(n)]


def _derrotas(n=6):
    return [_p(i + 3, "D", 0, 3) for i in range(n)]


def test_el_mas_reciente_pesa_uno():
    pesos = _pesos_recencia(6)
    assert pesos[-1] == 1.0
    assert pesos[0] < pesos[-1]  # el mas antiguo pesa menos (bug invertido)


def test_victorias_recientes_pesan_mas_que_las_antiguas():
    """Regresion del bug: mismos 6 resultados, solo cambia el orden."""
    base = [("D", 0, 2), ("D", 0, 2), ("D", 0, 2),
            ("V", 2, 0), ("V", 2, 0), ("V", 2, 0)]
    recientes = [_p(i, r, gf, gc) for i, (r, gf, gc) in enumerate(base)]
    antiguos = [_p(i, r, gf, gc) for i, (r, gf, gc) in enumerate(reversed(base))]
    nivel_recientes, _, _ = _calcular_nivel_actual(recientes, True)
    nivel_antiguos, _, _ = _calcular_nivel_actual(antiguos, True)
    assert nivel_recientes > nivel_antiguos


def test_menos_de_4_partidos_no_calcula():
    assert _calcular_nivel_actual(_victorias(3), True) == (None, None, 0)
    assert _calcular_nivel_actual([], True) == (None, None, 0)


def test_todo_victorias_cerca_de_10():
    poder, color, n = _calcular_nivel_actual(_victorias(6), True)
    assert 9.0 <= poder <= 10.0
    assert color == "🔵"
    assert n == 6


def test_todo_derrotas_cerca_de_0():
    poder, color, n = _calcular_nivel_actual(_derrotas(6), True)
    assert 0.0 <= poder < 2.0
    assert color == "🔴"


def test_sin_partidos_en_esa_sede_usa_el_global():
    historia_visitante = [_p(i, "V", 2, 0, es_local=False) for i in range(6)]
    poder, color, n = _calcular_nivel_actual(historia_visitante, True)
    assert poder is not None and 0 <= poder <= 10
    assert n == 6


def test_historial_desordenado_da_lo_mismo():
    historia = _victorias(3) + _derrotas(3)
    desordenada = historia.copy()
    random.Random(7).shuffle(desordenada)
    assert _calcular_nivel_actual(desordenada, True) == _calcular_nivel_actual(historia, True)


def test_helpers_misma_escala():
    todo_v = _victorias(6)
    assert _forma_0_100(todo_v) == 100.0
    assert _goles_0_100(todo_v) == 100.0  # diff 3 goles/parto: clamp 100
    todo_d = _derrotas(6)
    assert _forma_0_100(todo_d) == 0.0
    assert _goles_0_100(todo_d) == 0.0

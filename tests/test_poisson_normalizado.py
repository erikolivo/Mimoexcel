"""Tarea 9: la matriz de marcadores renormalizada suma exactamente 1."""
import pytest

from poisson_model import matriz_marcadores, probabilidades_1x2


@pytest.mark.parametrize("lam_local,lam_visitante", [
    (1.35, 1.35),
    (0.2, 3.5),
    (3.5, 0.2),
    (3.5, 3.5),
    (6.0, 6.0),
])
def test_probabilidades_1x2_suman_uno(lam_local, lam_visitante):
    matriz = matriz_marcadores(lam_local, lam_visitante)
    p_local, p_empate, p_visitante = probabilidades_1x2(matriz)
    assert abs((p_local + p_empate + p_visitante) - 1.0) < 1e-9


def test_celdas_no_negativas():
    matriz = matriz_marcadores(4.5, 2.0)
    assert all(p >= 0 for p in matriz.values())
    assert abs(sum(matriz.values()) - 1.0) < 1e-9


def test_sin_renormalizar_habria_sido_menos_de_uno():
    import math
    lam_l, lam_v, cortes = 3.5, 3.5, 6
    crudo = 0.0
    for gl in range(cortes + 1):
        for gv in range(cortes + 1):
            pl = (lam_l ** gl) * math.exp(-lam_l) / math.factorial(gl)
            pv = (lam_v ** gv) * math.exp(-lam_v) / math.factorial(gv)
            crudo += pl * pv
    assert crudo < 1.0  # el corte deja cola fuera...
    matriz = matriz_marcadores(lam_l, lam_v)
    assert abs(sum(matriz.values()) - 1.0) < 1e-9  # ...y la suma ahora es 1

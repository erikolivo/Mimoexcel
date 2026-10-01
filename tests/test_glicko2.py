"""Verificacion del algoritmo Glicko-2 contra el ejemplo del paper de
Mark Glickman (tau = 0.5, la referencia del modulo)."""
import glicko2


def test_ejemplo_del_paper_glickman():
    rating, rd, vol = glicko2.actualizar_rating(
        1500.0, 200.0, 0.06,
        [(1400.0, 30.0, 1.0),    # victoria
         (1550.0, 100.0, 0.0),   # derrota
         (1700.0, 300.0, 0.0)],  # derrota
    )
    assert abs(rating - 1464.06) < 0.05
    assert abs(rd - 151.52) < 0.05
    assert abs(vol - 0.05999) < 1e-4


def test_empate_es_medio_punto():
    rating, rd, vol = glicko2.actualizar_rating(
        1500.0, 200.0, 0.06, [(1500.0, 200.0, 0.5)])
    # Empatar contra un rival del mismo nivel no mueve el rating.
    assert abs(rating - 1500.0) < 1.0
    assert rd < 200.0  # el RD baja al jugar (incertidumbre que se resuelve)

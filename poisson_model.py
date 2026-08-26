"""
poisson_model.py
-----------------
SIN CAMBIOS por la migracion a ESPN -- calcula la expectativa
PRE-PARTIDO (goles esperados, probabilidad 1X2) usando Poisson, a
partir del rating combinado (ClubElo + Glicko-2) y el Goal Index. No
depende de que proveedor de datos en vivo se use.
"""

import math
from functools import lru_cache

VENTAJA_LOCAL_ELO = 70
PROMEDIO_GOLES_LIGA = 1.35
PESO_ELO_EN_GOLES = 1 / 200

PROB_MINIMA_FAVORITO = 0.65


def aplicar_rd(rating, rd):
    factor = max(0.0, min(1.0, 1.0 - (rd - 50) / 300))
    return 1500.0 + (rating - 1500.0) * factor


def cumple_filtro_cuota(evaluacion):
    return evaluacion["probabilidad"] >= PROB_MINIMA_FAVORITO


def goles_esperados(rating_local, rd_local, rating_visitante, rd_visitante,
                    goal_index_local_dict=None, goal_index_visitante_dict=None,
                    ventaja_local=VENTAJA_LOCAL_ELO, promedio_liga=PROMEDIO_GOLES_LIGA):

    rating_efectivo_local = aplicar_rd(rating_local, rd_local)
    rating_efectivo_visitante = aplicar_rd(rating_visitante, rd_visitante)

    diff_rating = (rating_efectivo_local + ventaja_local) - rating_efectivo_visitante
    ajuste_rating = diff_rating * PESO_ELO_EN_GOLES

    if goal_index_local_dict and goal_index_visitante_dict:
        base_local = (goal_index_local_dict.get("goles_favor_prom", promedio_liga) +
                      goal_index_visitante_dict.get("goles_contra_prom", promedio_liga)) / 2
        base_visitante = (goal_index_visitante_dict.get("goles_favor_prom", promedio_liga) +
                          goal_index_local_dict.get("goles_contra_prom", promedio_liga)) / 2
    else:
        base_local = promedio_liga
        base_visitante = promedio_liga

    gi_local_val = goal_index_local_dict.get("goal_index", 0) if goal_index_local_dict else 0
    gi_visitante_val = goal_index_visitante_dict.get("goal_index", 0) if goal_index_visitante_dict else 0

    lambda_local = max(0.15, base_local + ajuste_rating / 2 + gi_local_val / 2 - gi_visitante_val / 4)
    lambda_visitante = max(0.15, base_visitante - ajuste_rating / 2 + gi_visitante_val / 2 - gi_local_val / 4)

    return lambda_local, lambda_visitante


@lru_cache(maxsize=None)
def _poisson_pmf(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def matriz_marcadores(lambda_local, lambda_visitante, max_goles=6):
    matriz = {}
    for gl in range(max_goles + 1):
        for gv in range(max_goles + 1):
            matriz[(gl, gv)] = _poisson_pmf(gl, round(lambda_local, 4)) * _poisson_pmf(gv, round(lambda_visitante, 4))
    return matriz


def probabilidades_1x2(matriz):
    p_local = sum(p for (gl, gv), p in matriz.items() if gl > gv)
    p_empate = sum(p for (gl, gv), p in matriz.items() if gl == gv)
    p_visitante = sum(p for (gl, gv), p in matriz.items() if gl < gv)
    return p_local, p_empate, p_visitante


def evaluar_favorito(rating_local, rd_local, rating_visitante, rd_visitante,
                     goal_index_local_dict=None, goal_index_visitante_dict=None):

    lam_local, lam_visitante = goles_esperados(
        rating_local, rd_local, rating_visitante, rd_visitante,
        goal_index_local_dict, goal_index_visitante_dict
    )

    matriz = matriz_marcadores(lam_local, lam_visitante)
    p_local, p_empate, p_visitante = probabilidades_1x2(matriz)

    if p_local >= p_visitante:
        lado, prob = "local", p_local
    else:
        lado, prob = "visitante", p_visitante

    return {
        "lado": lado,
        "probabilidad": prob,
        "cuota_inicial": round(1 / prob, 2) if prob > 0 else None,
        "lambda_local": round(lam_local, 3),
        "lambda_visitante": round(lam_visitante, 3),
        # NUEVO (a pedido explicito): cuota del modelo propio para AMBOS
        # lados, no solo el favorito -- resumen.py las muestra las dos
        # para que la persona pueda comparar. Se ignora el empate en
        # estos dos calculos, igual que en el resto del sistema.
        "probabilidad_local": p_local,
        "probabilidad_visitante": p_visitante,
        "cuota_local": round(1 / p_local, 2) if p_local > 0 else None,
        "cuota_visitante": round(1 / p_visitante, 2) if p_visitante > 0 else None,
    }


def probabilidad_favorito_en_vivo(lambda_local, lambda_visitante, goles_local_actual, goles_visitante_actual,
                                   minuto_actual, favorito_es_local, minutos_partido=90):
    minutos_restantes = max(0, minutos_partido - minuto_actual)
    fraccion = minutos_restantes / minutos_partido

    lam_local_restante = lambda_local * fraccion
    lam_visitante_restante = lambda_visitante * fraccion

    matriz_restante = matriz_marcadores(lam_local_restante, lam_visitante_restante, max_goles=6)

    prob_favorito_gana = 0.0
    for (gl_restante, gv_restante), p in matriz_restante.items():
        gl_final = goles_local_actual + gl_restante
        gv_final = goles_visitante_actual + gv_restante
        if favorito_es_local:
            gana_favorito = gl_final > gv_final
        else:
            gana_favorito = gv_final > gl_final
        if gana_favorito:
            prob_favorito_gana += p

    return prob_favorito_gana

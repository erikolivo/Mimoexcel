"""T2 — Resolucion de alertas (resolucion_alertas.resolver_pendientes).

Fixtures sinteticos escritos a mano; no leen data/.
"""
import copy

import resolucion_alertas as R


def snap(minuto, gl=0, gv=0, periodo=None):
    s = {"minuto": minuto, "goles_local": gl, "goles_visitante": gv,
         "stats_local": {}, "stats_visitante": {}}
    if periodo is not None:
        s["periodo"] = periodo
    return s


def partido_base(fav_local=True):
    return {"local": "Sevilla", "visitante": "Betis",
            "favorito": "Sevilla", "no_favorito": "Betis",
            "favorito_es_local": fav_local, "alertas_enviadas": []}


def alerta(tipo, minuto, lado="fav", criterio="siguiente_gol"):
    return {"tipo": tipo, "minuto": minuto, "texto": "x", "diferencia_goles": 0,
            "id": "t-0", "minuto_int": int(minuto.rstrip("'")), "marcador_alerta": [0, 0],
            "lado": lado, "criterio": criterio, "estado": "pendiente",
            "resuelta_minuto": None, "resuelta_motivo": None,
            "resolucion_notificada": False, "acierto": None}


def test_acierto_por_gol_del_favorito():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("posible_victoria_favorito", "34'")]
    res = R.resolver_pendientes(p, snap("34'", 0, 0), snap("41'", 1, 0))
    assert len(res) == 1
    assert res[0]["estado"] == "acierto" and res[0]["acierto"] is True
    assert res[0]["resuelta_motivo"] == "gol_fav"
    assert res[0]["resuelta_minuto"] == 41


def test_fallo_por_gol_del_rival():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("posible_victoria_favorito", "34'")]
    res = R.resolver_pendientes(p, snap("34'", 0, 0), snap("50'", 0, 1))
    assert res[0]["estado"] == "fallo" and res[0]["acierto"] is False
    assert res[0]["resuelta_motivo"] == "gol_rival"


def test_fallo_sin_mas_goles_al_terminar():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("gol_de_cierre", "78'")]
    res = R.resolver_pendientes(p, snap("78'", 1, 1), snap("90'+3'", 1, 1),
                                terminado=True, marcador_final=(1, 1))
    assert res[0]["estado"] == "fallo"
    assert res[0]["resuelta_motivo"] == "sin_mas_goles"


def test_ambiguo_si_marcan_ambos():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("ampliacion_marcador", "60'")]
    res = R.resolver_pendientes(p, snap("60'", 1, 0), snap("65'", 2, 1))
    assert res[0]["estado"] == "ambiguo" and res[0]["acierto"] is None
    assert res[0]["resuelta_motivo"] == "ambos_marcaron"


def test_dos_alertas_iguales_se_resuelven_ambas():
    # B3: antes la segunda sobrescribia a la primera.
    p = partido_base()
    p["alertas_enviadas"] = [alerta("posible_victoria_favorito", "20'"),
                             alerta("posible_victoria_favorito", "34'")]
    res = R.resolver_pendientes(p, snap("34'", 0, 0), snap("41'", 1, 0))
    assert len(res) == 2
    assert all(a["estado"] == "acierto" for a in res)


def test_ventana_15_acierta_y_vence():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("cuidado_rival_presiona", "52'", lado="rival", criterio="ventana_15")]
    res = R.resolver_pendientes(p, snap("52'", 0, 0), snap("60'", 0, 1))
    assert res[0]["estado"] == "acierto"
    p2 = partido_base()
    p2["alertas_enviadas"] = [alerta("cuidado_rival_presiona", "52'", lado="rival", criterio="ventana_15")]
    res2 = R.resolver_pendientes(p2, snap("60'", 0, 0), snap("70'", 0, 0))
    assert res2[0]["estado"] == "fallo"
    assert res2[0]["resuelta_motivo"] == "ventana_vencida"


def test_gol_del_favorito_no_resuelve_ventana_rival():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("cuidado_rival_presiona", "52'", lado="rival", criterio="ventana_15")]
    res = R.resolver_pendientes(p, snap("52'", 0, 0), snap("60'", 1, 0))
    assert res == []
    assert p["alertas_enviadas"][0]["estado"] == "pendiente"


def test_fin_1t_acierta_con_gol_38():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("alerta_1er_tiempo", "25'", criterio="fin_1t")]
    res = R.resolver_pendientes(p, snap("25'", 0, 0, periodo=1), snap("38'", 1, 0, periodo=1))
    assert res[0]["estado"] == "acierto"


def test_fin_1t_falla_al_llegar_2t():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("alerta_1er_tiempo", "25'", criterio="fin_1t")]
    res = R.resolver_pendientes(p, snap("45'", 0, 0, periodo=1), snap("47'", 0, 0, periodo=2))
    assert res[0]["estado"] == "fallo"
    assert res[0]["resuelta_motivo"] == "fin_1t"


def test_gol_solo_visible_en_2t_no_cuenta_1t():
    p = partido_base()
    p["alertas_enviadas"] = [alerta("alerta_1er_tiempo", "25'", criterio="fin_1t")]
    res = R.resolver_pendientes(p, snap("45'", 0, 0, periodo=1), snap("47'", 1, 0, periodo=2))
    assert res[0]["estado"] == "fallo"


def test_gol_anterior_a_la_alerta_no_resuelve():
    p = partido_base()
    # La alerta se registra en 34'; el ciclo trae snap 30'->34' SIN goles nuevos
    # (el gol fue anterior). No debe resolverse.
    p["alertas_enviadas"] = [alerta("posible_victoria_favorito", "34'")]
    res = R.resolver_pendientes(p, snap("30'", 1, 0), snap("34'", 1, 0))
    assert res == []


def test_evaluar_alerta_reproduce_en_historial():
    h = [snap("20'", 0, 0), snap("34'", 0, 0), snap("41'", 1, 0), snap("90'", 1, 0)]
    a = alerta("posible_victoria_favorito", "34'")
    assert R.evaluar_alerta(h, a, True, marcador_final=(1, 0)) is True
    h2 = [snap("20'", 0, 0), snap("34'", 0, 0), snap("50'", 0, 1)]
    assert R.evaluar_alerta(h2, copy.deepcopy(a), True, marcador_final=(0, 1)) is False


# ── Regresión 2026-09: efectividad agrupa por partido ──────────────────────

def _resuelta(tipo, minuto, estado):
    if minuto == "90'+5'":
        a = alerta(tipo, "70'")
        a["minuto"] = "90'+5'"
        a["minuto_int"] = None
    else:
        a = alerta(tipo, minuto)
    a["estado"] = estado
    a["acierto"] = True if estado == "acierto" else (False if estado == "fallo" else None)
    return a


def test_efectividad_hoy_agrupa_mismo_partido():
    """Dos alertas del mismo tipo en el mismo partido cuentan COMO UNA
    (mayoría decide), igual que la hoja del Excel. Regresión: la pareja
    70' + 90'+5' de fav_domina_no_gana se contaba como DOS fallos."""
    p = partido_base()
    p["alertas_enviadas"] = [_resuelta("fav_domina_no_gana", "70'", "fallo"),
                             _resuelta("fav_domina_no_gana", "90'+5'", "fallo")]
    assert R.efectividad_hoy([p], "fav_domina_no_gana") == (0, 1)


def test_efectividad_hoy_partidos_distintos_se_suman():
    """Cada partido aporta una sola unidad por tipo."""
    p1 = partido_base()
    p1["alertas_enviadas"] = [_resuelta("fav_domina_no_gana", "70'", "fallo"),
                              _resuelta("fav_domina_no_gana", "90'+5'", "fallo")]
    p2 = partido_base()
    p2["alertas_enviadas"] = [_resuelta("fav_domina_no_gana", "30'", "acierto")]
    assert R.efectividad_hoy([p1, p2], "fav_domina_no_gana") == (1, 1)


def test_efectividad_hoy_mixto_decide_mayoria():
    """Acierto + fallo del mismo tipo/partido: mayoría decide; empate 1-1
    cuenta como fallo (misma regla que cerrar_resultados.py)."""
    p = partido_base()
    p["alertas_enviadas"] = [_resuelta("posible_victoria_favorito", "20'", "acierto"),
                             _resuelta("posible_victoria_favorito", "45'", "fallo")]
    assert R.efectividad_hoy([p], "posible_victoria_favorito") == (0, 1)
    p["alertas_enviadas"].append(_resuelta("posible_victoria_favorito", "60'", "acierto"))
    assert R.efectividad_hoy([p], "posible_victoria_favorito") == (1, 0)


def test_efectividad_hoy_excluye_ambiguas_y_otros_tipos():
    """Ambiguas/pendientes no cuentan; los otros tipos se ignoran."""
    p = partido_base()
    p["alertas_enviadas"] = [_resuelta("fav_domina_no_gana", "50'", "ambiguo"),
                             _resuelta("fav_domina_no_gana", "60'", "pendiente"),
                             _resuelta("ampliacion_marcador", "55'", "acierto")]
    assert R.efectividad_hoy([p], "fav_domina_no_gana") == (0, 0)
    assert R.efectividad_hoy([p], "ampliacion_marcador") == (1, 0)

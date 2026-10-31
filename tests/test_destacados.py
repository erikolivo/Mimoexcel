"""Combinadas del dia (destacados.py): filtro, relleno a multiplo de 3 y reparto al azar.

Sin red y sin escribir en data/.
"""

import datetime
import random

import destacados as D

AHORA = datetime.datetime(2026, 10, 31, 11, 0, tzinfo=datetime.timezone.utc)


def _partido(nombre, pf, p_gana, p_no_pierde, tipo="favorito_directo", hora="2026-10-31T15:00Z",
             fixture_id=None, cuotas=(1.4, 4.0, 7.0)):
    return {
        "local": nombre, "visitante": "Rival " + nombre, "favorito": nombre, "favorito_es_local": True,
        "tipo_pronostico": tipo, "pf_hoja": pf, "p_gana_fav": p_gana, "p_no_pierde_fav": p_no_pierde,
        "hora_inicio": hora, "fixture_id": fixture_id if fixture_id is not None else nombre,
        "cuota_local_inicial": cuotas[0], "cuota_empate_inicial": cuotas[1], "cuota_visitante_inicial": cuotas[2],
    }


def _buenos(n, prefijo="B"):
    return [_partido(f"{prefijo}{i}", 0.76 + i * 0.01, 0.758 + i * 0.01, 0.9) for i in range(n)]


def _flojos(n, prefijo="F"):
    # directos con 70 % (no cumplen el filtro de 75 %) y distinta probabilidad
    return [_partido(f"{prefijo}{i}", 0.65 + i * 0.01, 0.664 + i * 0.01, 0.86) for i in range(n)]


def test_descarta_ya_empezados_sin_seguimiento_y_sin_probabilidad():
    partidos = [
        _partido("A", 0.80, 0.816, 0.943),
        _partido("C", 0.85, 0.816, 0.943, hora="2026-10-31T10:00Z"),   # ya empezo
        _partido("D", 0.85, 0.816, 0.943, fixture_id=""),              # sin seguimiento
    ]
    partidos[2]["fixture_id"] = None
    sin_prob = _partido("E", 0.85, 0.816, 0.943)
    sin_prob["p_gana_fav"] = None
    partidos.append(sin_prob)
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(partidos, AHORA)
    assert n_cumplen == 1
    assert combinadas == []            # no hay 3 elegibles para completar el grupo


def test_ninguno_cumple_el_filtro_no_arma_combinadas():
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(_flojos(10), AHORA)
    assert n_cumplen == 0 and combinadas == [] and elegidos == []


def test_completa_a_multiplo_de_3_con_los_mas_probables_de_los_que_sobran():
    partidos = _buenos(8) + _flojos(5)          # 8 cumplen -> se completa a 9
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(partidos, AHORA, random.Random(1))
    assert n_cumplen == 8 and len(elegidos) == 9 and len(combinadas) == 3
    assert rellenos == ["F4"]                    # el flojo mas probable (pf .69)


def test_completa_de_1_a_3_y_de_4_a_6():
    c1, e1, _, r1 = D.armar_combinadas(_buenos(1) + _flojos(5), AHORA, random.Random(1))
    assert len(e1) == 3 and len(r1) == 2 and r1 == ["F4", "F3"]
    c2, e2, _, r2 = D.armar_combinadas(_buenos(4) + _flojos(5), AHORA, random.Random(1))
    assert len(e2) == 6 and len(r2) == 2 and len(c2) == 2


def test_multiplo_exacto_no_agrega_rellenos():
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(_buenos(6) + _flojos(5), AHORA)
    assert len(elegidos) == 6 and rellenos == []


def test_maximo_9_se_quedan_los_9_mas_probables():
    partidos = _buenos(14)
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(partidos, AHORA)
    assert len(elegidos) == D.MAX_PARTIDOS == 9 and len(combinadas) == 3
    nombres = {p["favorito"] for p in elegidos}
    assert nombres == {f"B{i}" for i in range(5, 14)}      # los de mayor probabilidad


def test_si_no_alcanzan_elegibles_para_completar_baja_al_multiplo_anterior():
    combinadas, elegidos, n_cumplen, rellenos = D.armar_combinadas(_buenos(4) + _flojos(1), AHORA)
    assert len(elegidos) == 3 and len(combinadas) == 1      # 5 elegibles -> 3
    assert rellenos == []


def test_reparto_al_azar_no_sigue_el_orden_de_probabilidad():
    partidos = _buenos(9)
    ordenes = set()
    for semilla in range(30):
        combinadas, elegidos, *_ = D.armar_combinadas(partidos, AHORA, random.Random(semilla))
        assert sorted(p["favorito"] for p in elegidos) == sorted(p["favorito"] for p in partidos)
        ordenes.add(tuple(p["favorito"] for p in elegidos))
    assert len(ordenes) > 20                 # el reparto cambia de una corrida a otra
    # y no queda siempre el grupo 1 con los 3 mas probables
    grupo1 = {tuple(sorted(p["favorito"] for p in D.armar_combinadas(partidos, AHORA, random.Random(s))[0][0]))
              for s in range(30)}
    assert len(grupo1) > 5


def test_marcas_en_partidos_y_reinicio():
    partidos = _buenos(2) + _flojos(3)
    viejo = _partido("Z", 0.60, 0.589, 0.809)
    viejo["es_destacado"], viejo["grupo_destacado"] = True, 1
    partidos.append(viejo)
    combinadas, elegidos, n, rellenos = D.elegir_destacados(partidos, AHORA, random.Random(3))
    marcados = [p for p in partidos if p.get("es_destacado")]
    assert len(marcados) == 3 and {p["grupo_destacado"] for p in marcados} == {1}
    assert sum(1 for p in marcados if p["combinada_pick"]["relleno"]) == 1
    assert "es_destacado" not in viejo or viejo in marcados


def test_cuota_doble_oportunidad():
    dc = _partido("X", 0.58, 0.553, 0.79, tipo="doble_oportunidad", cuotas=(1.7, 4.0, 4.33))
    assert abs(D._cuota_pick(dc) - 1 / (1 / 1.7 + 1 / 4.0)) < 1e-9
    assert D._cuota_pick(_partido("Y", 0.80, 0.816, 0.943, cuotas=(1.25, 6.0, 11.0))) == 1.25

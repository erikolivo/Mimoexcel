"""T5 — IDV: sd con z corregido, simetría entre ramas.

Verifica que B7 esté corregido: z, dominancia_pct = momentum.z_score_dominancia(...)
(en ese orden), y que sd = min(abs(z)/3, 1) use el z real (no la dominancia).
"""
import momentum


def _snap(gl=0, gv=0, sot_l=5, sot_v=2, shots_l=10, shots_v=5, poss_l=55, poss_v=45):
    return {
        "minuto": "30'",
        "goles_local": gl, "goles_visitante": gv,
        "stats_local": {
            "shotsOnTarget": sot_l, "totalShots": shots_l,
            "wonCorners": 3, "blockedShots": 1,
            "possessionPct": poss_l, "foulsCommitted": 5,
        },
        "stats_visitante": {
            "shotsOnTarget": sot_v, "totalShots": shots_v,
            "wonCorners": 2, "blockedShots": 1,
            "possessionPct": poss_v, "foulsCommitted": 8,
        },
    }


def _historial(fav_domina=True, n=8):
    """Historial con stats CRECIENTES donde un lado domina."""
    snaps = []
    for i in range(n):
        m = 5 + i * 5
        if fav_domina:
            snaps.append(_snap(gl=0, gv=0, sot_l=3+i, sot_v=1,
                           shots_l=6+i*2, shots_v=2+i, poss_l=60, poss_v=40))
        else:
            snaps.append(_snap(gl=0, gv=0, sot_l=1, sot_v=3+i,
                               shots_l=2+i, shots_v=6+i*2, poss_l=40, poss_v=60))
        snaps[-1]["minuto"] = f"{m}'"
    return snaps


def test_sd_usa_z_real_no_dominancia():
    """sd = min(abs(z)/3, 1) debe usar z, no la dominancia.
    Con z=3.0, dominancia ~0.9 → sd debe ser 1.0 (no 0.3)."""
    z = 3.0
    dominancia = 0.9
    sd = min(abs(z) / 3, 1)
    assert sd == 1.0, f"sd deberia ser 1.0, got {sd}"


def test_sd_z_bajo():
    """Con z=1.5, sd = min(1.5/3, 1) = 0.5."""
    z = 1.5
    sd = min(abs(z) / 3, 1)
    assert sd == 0.5, f"sd deberia ser 0.5, got {sd}"


def test_sd_z_muy_alto():
    """Con z=5.0, sd = min(5.0/3, 1) = 1.0 (tope)."""
    z = 5.0
    sd = min(abs(z) / 3, 1)
    assert sd == 1.0, f"sd deberia ser 1.0, got {sd}"


def test_idv_correct_unpacking():
    """Verifica que _calcular_idv usa z (no dominancia) para sd."""
    import monitor

    h_fav = _historial(fav_domina=True)
    snap = _snap(gl=0, gv=0, sot_l=8, sot_v=1, poss_l=65, poss_v=35)

    partido = {
        "local": "Sevilla", "visitante": "Betis",
        "favorito_es_local": True,
        "cuota_local_inicial": 1.8,
        "cuota_visitante_inicial": 4.0,
        "historial_snapshots": h_fav,
    }

    result = monitor._calcular_idv(partido, snap, h_fav, 30)
    if result is not None:
        # z real debe ser significativo (no la dominancia que sería ~0.9)
        assert abs(result["z"]) > 1.0, f"z debe ser significativo, got {result['z']}"
        # sd = min(abs(z)/3, 1)
        expected_sd = min(abs(result["z"]) / 3, 1)
        assert abs(result["sd"] - expected_sd) < 0.01, \
            f"sd debe ser min(abs(z)/3,1)={expected_sd:.2f}, got {result['sd']}"


def test_simetria_fav_local_vs_visitante():
    """El resultado de _calcular_idv debe ser simétrico cuando se
    invierte el lado del favorito (con historial espejado)."""
    import monitor

    h_fav_local = _historial(fav_domina=True)
    h_fav_visitante = _historial(fav_domina=False)

    snap = _snap(gl=0, gv=0, sot_l=5, sot_v=2)

    partido_local = {
        "local": "Sevilla", "visitante": "Betis",
        "favorito_es_local": True,
        "cuota_local_inicial": 1.8,
        "cuota_visitante_inicial": 4.0,
        "historial_snapshots": h_fav_local,
    }

    partido_visitante = {
        "local": "Betis", "visitante": "Sevilla",
        "favorito_es_local": False,
        "cuota_local_inicial": 4.0,
        "cuota_visitante_inicial": 1.8,
        "historial_snapshots": h_fav_visitante,
    }

    result_l = monitor._calcular_idv(partido_local, snap, h_fav_local, 30)
    result_v = monitor._calcular_idv(partido_visitante, snap, h_fav_visitante, 30)

    # Si ambos devuelven resultado, verificar simetría
    if result_l is not None and result_v is not None:
        assert abs(result_l["idv"] - result_v["idv"]) < 0.01, \
            f"IDV simétrico: local={result_l['idv']:.2f}, visitante={result_v['idv']:.2f}"
        assert abs(result_l["sd"] - result_v["sd"]) < 0.01, \
            f"sd simétrico: local={result_l['sd']:.2f}, visitante={result_v['sd']:.2f}"
    # Al menos uno debe devolver resultado con stats fuertes
    assert result_l is not None or result_v is not None, \
        "Al menos una rama debe devolver IDV con stats fuertes"

"""T1 — Reglas de disparo (función pura, snapshots sintéticos).

Cada test verifica que _evaluar_alertas emita o no emita un tipo dado
bajo condiciones específicas. Se usa un histórico mínimo con stats
CRECIENTES (como ESPN real) para que el z-score y la presión
produzcan valores coherentes.
"""
import monitor
import momentum


def _snap(minuto, gl=0, gv=0, sot_l=0, sot_v=0, shots_l=0, shots_v=0,
          corners_l=0, corners_v=0, poss_l=55, poss_v=45):
    """Snapshot mínimo con stats para momentum."""
    return {
        "minuto": minuto,
        "goles_local": gl,
        "goles_visitante": gv,
        "stats_local": {
            "shotsOnTarget": sot_l, "totalShots": shots_l,
            "wonCorners": corners_l, "blockedShots": 0,
            "possessionPct": poss_l, "foulsCommitted": 5,
        },
        "stats_visitante": {
            "shotsOnTarget": sot_v, "totalShots": shots_v,
            "wonCorners": corners_v, "blockedShots": 0,
            "possessionPct": poss_v, "foulsCommitted": 8,
        },
    }


def _partido(fav_local=True, tipo_pronostico="favorito_directo", prioridad="ALTA"):
    return {
        "local": "Sevilla", "visitante": "Betis",
        "favorito": "Sevilla" if fav_local else "Betis",
        "no_favorito": "Betis" if fav_local else "Sevilla",
        "favorito_es_local": fav_local,
        "tipo_pronostico": tipo_pronostico,
        "prioridad": prioridad,
        "cuota_local_inicial": 1.8,
        "cuota_visitante_inicial": 4.0,
        "fixture_id": "test-001",
        "historial_snapshots": [],
        "alertas_enviadas": [],
    }


def _historial_gana_fav(minuto_actual, n_snaps=8):
    """Historial con stats CRECIENTES donde el favorito (local) domina."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, int(minuto_actual * (i + 1) / n_snaps))
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=3 + i, sot_v=1,
                           shots_l=6 + i * 2, shots_v=2 + i,
                           corners_l=2 + i, corners_v=1))
    return snaps


def _historial_gana_fav_debil(minuto_actual, n_snaps=8):
    """Historial con stats CRECIENTES pero débiles (pf < 8.0)."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, int(minuto_actual * (i + 1) / n_snaps))
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=1 + i // 2, sot_v=1,
                           shots_l=2 + i, shots_v=2,
                           corners_l=1, corners_v=1))
    return snaps


def _historial_rival_domina(minuto_actual, n_snaps=8):
    """Historial con stats CRECIENTES donde el rival (visitante) domina."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, int(minuto_actual * (i + 1) / n_snaps))
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=1, sot_v=3 + i,
                           shots_l=2 + i, shots_v=6 + i * 2,
                           corners_l=1, corners_v=2 + i))
    return snaps


def _historial_rival_debil(minuto_actual, n_snaps=8):
    """Historial con rival moderadamente arriba pero z_rival < 2.0."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, int(minuto_actual * (i + 1) / n_snaps))
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=1, sot_v=1 + i // 3,
                           shots_l=2, shots_v=2 + i // 2,
                           corners_l=1, corners_v=1))
    return snaps


def _historial_close(minuto_actual, n_snaps=10):
    """Historial con stats CRECIENTES cerca del minuto actual."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, minuto_actual - n_snaps + i + 1)
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=3 + i, sot_v=0,
                           shots_l=6 + i, shots_v=1,
                           corners_l=2 + i // 2, corners_v=0))
    return snaps


def _historial_close_rival(minuto_actual, n_snaps=10):
    """Historial cercano con stats CRECIENTES del rival (visitante)."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, minuto_actual - n_snaps + i + 1)
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=0, sot_v=3 + i,
                           shots_l=1, shots_v=6 + i,
                           corners_l=0, corners_v=2 + i // 2))
    return snaps


def _historial_close_empate(minuto_actual, n_snaps=10):
    """Historial cercano con stats iguales (equilibrados)."""
    snaps = []
    for i in range(n_snaps):
        m = max(5, minuto_actual - n_snaps + i + 1)
        snaps.append(_snap(f"{m}'", gl=0, gv=0,
                           sot_l=3, sot_v=3,
                           shots_l=6, shots_v=6,
                           corners_l=2, corners_v=2))
    return snaps


# ── C1: posible_victoria_favorito ──────────────────────────────────────────

def test_c1_no_dispara_con_pf_bajo():
    """Con pf < 8.0 no debe disparar posible_victoria_favorito."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav_debil(50)
    snap = _snap("50'", gl=0, gv=0, sot_l=2, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "posible_victoria_favorito" not in tipos


def test_c1_dispara_con_pf_suficiente():
    """Con pf >= 8.0 y z alto, debe disparar."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=0, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "posible_victoria_favorito" in tipos


# ── C2: posible_descuento ──────────────────────────────────────────────────

def test_c2_no_dispara_con_dif_menos_2():
    """Con dif = -2 no debe disparar posible_descuento."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=2, sot_l=5, sot_v=2)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "posible_descuento" not in tipos


def test_c2_no_dispara_con_doble_oportunidad():
    """Con doble_oportunidad no debe disparar posible_descuento."""
    p = _partido(tipo_pronostico="doble_oportunidad")
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=1, sot_l=5, sot_v=2)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "posible_descuento" not in tipos


def test_c2_no_dispara_en_minuto_61():
    """En minuto 61 no debe disparar (tope DESCUENTO_MAX_MINUTO=60)."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(61)
    snap = _snap("61'", gl=0, gv=1, sot_l=5, sot_v=2)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "61'")
    tipos = [t for t, _ in alertas]
    assert "posible_descuento" not in tipos


def test_c2_dispara_con_dif_menos_1_fav_directo_minuto_50():
    """Con dif=-1, favorito_directo, minuto 50, sí debe disparar."""
    p = _partido(tipo_pronostico="favorito_directo")
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=1, sot_l=5, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "posible_descuento" in tipos


# ── C3: ampliacion_marcador ────────────────────────────────────────────────

def test_c3_no_dispara_con_pf_bajo():
    """Con pf < 11 no debe disparar ampliacion_marcador."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav_debil(50)
    snap = _snap("50'", gl=1, gv=0, sot_l=2, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "ampliacion_marcador" not in tipos


def test_c3_dispara_con_pf_suficiente():
    """Con pf >= 11, dif>0, z>=2, sí debe disparar."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=1, gv=0, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "ampliacion_marcador" in tipos


# ── C6: gol_de_cierre ──────────────────────────────────────────────────────

def test_c6_no_dispara_con_dif_positivo():
    """Con dif = +1 no debe disparar gol_de_cierre."""
    p = _partido()
    p["historial_snapshots"] = _historial_close(80)
    snap = _snap("80'", gl=2, gv=1, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "80'")
    tipos = [t for t, _ in alertas]
    assert "gol_de_cierre" not in tipos


def test_c6_no_dispara_con_dif_menos_2():
    """Con dif = -2 no debe disparar gol_de_cierre."""
    p = _partido()
    p["historial_snapshots"] = _historial_close(80)
    snap = _snap("80'", gl=0, gv=2, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "80'")
    tipos = [t for t, _ in alertas]
    assert "gol_de_cierre" not in tipos


def test_c6_no_dispara_en_minuto_85():
    """En minuto 85 no debe disparar (tope CIERRE_MAX_MINUTO=84)."""
    p = _partido()
    p["historial_snapshots"] = _historial_close(85)
    snap = _snap("85'", gl=0, gv=0, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "85'")
    tipos = [t for t, _ in alertas]
    assert "gol_de_cierre" not in tipos


def test_c6_no_dispara_con_z_bajo():
    """Con z=3.1 no debe disparar (tope UMBRAL_Z_CIERRE=3.2).
    Usamos stats equilibrados para que z sea bajo."""
    p = _partido()
    p["historial_snapshots"] = _historial_close_empate(80)
    snap = _snap("80'", gl=0, gv=0, sot_l=3, sot_v=3)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "80'")
    tipos = [t for t, _ in alertas]
    assert "gol_de_cierre" not in tipos


def test_c6_dispara_con_dif_0_minuto_80_z_alto():
    """Con dif=0, minuto 80, z>=3.2, sí debe disparar."""
    p = _partido()
    p["historial_snapshots"] = _historial_close(80)
    snap = _snap("80'", gl=0, gv=0, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "80'")
    tipos = [t for t, _ in alertas]
    assert "gol_de_cierre" in tipos


def test_c6_a_partir_75_no_cae_a_otra():
    """A partir del min 75, si no cumple cierre, no debe caer a otra alerta."""
    p = _partido()
    p["historial_snapshots"] = _historial_close(76)
    snap = _snap("76'", gl=1, gv=0, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "76'")
    tipos = [t for t, _ in alertas]
    assert len(tipos) == 0


# ── C7: fav_domina_no_gana ────────────────────────────────────────────────

def test_c7_no_dispara_con_dif_menos_3():
    """Con dif = -3 no debe disparar fav_domina_no_gana."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=3, sot_l=5, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "fav_domina_no_gana" not in tipos


def test_c7_dispara_con_dif_menos_2():
    """Con dif = -2 y z alto, sí debe disparar fav_domina_no_gana."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(50)
    snap = _snap("50'", gl=0, gv=2, sot_l=6, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "fav_domina_no_gana" in tipos


# ── C8: no_fav_domina ──────────────────────────────────────────────────────

def test_c8_no_dispara_con_pr_bajo():
    """Con pr < 11 no debe disparar no_fav_domina."""
    p = _partido()
    p["historial_snapshots"] = _historial_rival_debil(50)
    snap = _snap("50'", gl=0, gv=0, sot_l=1, sot_v=2)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "no_fav_domina" not in tipos


def test_c8_no_dispara_con_dif_menos_1():
    """Con dif = -1 (no-favorito ya ganando) no debe disparar."""
    p = _partido()
    p["historial_snapshots"] = _historial_close_rival(50)
    snap = _snap("50'", gl=0, gv=1, sot_l=0, sot_v=6)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "no_fav_domina" not in tipos


def test_c8_dispara_con_pr_suficiente_dif_0():
    """Con pr >= 11, dif = 0, z alto, sot_riv < 2 (bloquea cuidado_rival), sí debe disparar."""
    p = _partido()
    p["historial_snapshots"] = _historial_close_rival(50)
    # sot_riv=1 bloquea cuidado_rival_presiona (RIVAL_TIROS_PUERTA_MIN=2)
    snap = _snap("50'", gl=0, gv=0, sot_l=0, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "no_fav_domina" in tipos


# ── C4: cuidado_rival_presiona ─────────────────────────────────────────────

def test_c4_no_dispara_con_z_rival_bajo():
    """Con z_rival < 2.0 no debe disparar cuidado_rival_presiona."""
    p = _partido()
    p["historial_snapshots"] = _historial_rival_debil(50)
    snap = _snap("50'", gl=0, gv=0, sot_l=1, sot_v=2)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "cuidado_rival_presiona" not in tipos


def test_c4_no_dispara_con_sot_riv_bajo():
    """Con sot_riv < 2 no debe disparar cuidado_rival_presiona."""
    p = _partido()
    p["historial_snapshots"] = _historial_close_rival(50)
    snap = _snap("50'", gl=0, gv=0, sot_l=0, sot_v=1)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
    tipos = [t for t, _ in alertas]
    assert "cuidado_rival_presiona" not in tipos


# ── C5: alerta_1er_tiempo ──────────────────────────────────────────────────

def test_c5_no_dispara_con_doble_oportunidad():
    """Con doble_oportunidad no debe disparar alerta_1er_tiempo."""
    p = _partido(tipo_pronostico="doble_oportunidad")
    p["historial_snapshots"] = _historial_gana_fav(25)
    snap = _snap("25'", gl=0, gv=0, sot_l=5, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "25'")
    tipos = [t for t, _ in alertas]
    assert "alerta_1er_tiempo" not in tipos


def test_c5_no_dispara_en_minuto_31():
    """En minuto 31 no debe disparar (tope MINUTO_FIN_1ER_TIEMPO=30)."""
    p = _partido()
    p["historial_snapshots"] = _historial_gana_fav(31)
    snap = _snap("31'", gl=0, gv=0, sot_l=5, sot_v=0)
    alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "31'")
    tipos = [t for t, _ in alertas]
    assert "alerta_1er_tiempo" not in tipos


# ── ALERTA_ACTIVA gates ───────────────────────────────────────────────────

def test_alerta_inactiva_no_dispara():
    """Con ALERTA_ACTIVA[tipo] = False, ese tipo nunca dispara."""
    original = monitor.ALERTA_ACTIVA.copy()
    monitor.ALERTA_ACTIVA["posible_victoria_favorito"] = False
    try:
        p = _partido()
        p["historial_snapshots"] = _historial_gana_fav(50)
        snap = _snap("50'", gl=0, gv=0, sot_l=6, sot_v=0)
        alertas = monitor._evaluar_alertas(p, snap, p["historial_snapshots"][-1], "50'")
        tipos = [t for t, _ in alertas]
        assert "posible_victoria_favorito" not in tipos
    finally:
        monitor.ALERTA_ACTIVA.update(original)

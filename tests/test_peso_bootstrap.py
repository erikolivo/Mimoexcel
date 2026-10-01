"""Tarea 7: el bootstrap cuenta la mitad para el peso del blend
(n_efectivo = reales + 0.5 * bootstrap)."""
import json

import ratings_store


def _guardar_equipo(archivo, llave, reales, bootstrap, rating=1500.0,
                    rd=150.0):
    archivo.write_text(json.dumps({"equipos": {llave: {
        "nombre": "Equipo", "pais": None, "liga": "E0",
        "rating": rating, "rd": rd, "vol": 0.06,
        "partidos_jugados": reales + bootstrap,
        "partidos_bootstrap": bootstrap, "partidos_reales": reales,
        "ultima_actualizacion": "2026-01-01",
    }}}), encoding="utf-8")


def test_30_bootstrap_0_reales_usa_tramo_75(ratings_tmp):
    _guardar_equipo(ratings_tmp, "boot:E0|Team", reales=0, bootstrap=30)
    rating, n, rd = ratings_store.rating_combinado("boot:E0|Team", 1800.0)
    assert n == 30                       # el n reportado sigue siendo total
    # n_efectivo = 15 -> tramo 75%: 0.75*1500 + 0.25*1800 = 1575
    assert rating == 1575.0


def test_20_reales_sin_bootstrap_sigue_al_100(ratings_tmp):
    _guardar_equipo(ratings_tmp, "espn:200", reales=20, bootstrap=0,
                    rating=1600.0)
    rating, n, rd = ratings_store.rating_combinado("espn:200", 1800.0)
    assert n == 20
    assert rating == 1600.0              # peso 100%: solo rating propio


def test_10_reales_20_bootstrap_pesa_como_20_totales(ratings_tmp):
    _guardar_equipo(ratings_tmp, "boot:E0|Mixto", reales=10, bootstrap=20,
                    rating=1500.0)
    rating, n, rd = ratings_store.rating_combinado("boot:E0|Mixto", 1800.0)
    assert n == 30
    # n_efectivo = 10 + 10 = 20 -> tramo 100% (n_efectivo > 15)
    assert rating == 1500.0

"""Tarea 6b: calibracion de la escala propia de cada liga contra
ClubElo (ratings_store.calibrar_liga_a_clubelo + emparejamiento)."""
import json

import ratings_store
from bootstrap_ligas import pares_elo_desde_ranking


def _crear_equipos(ratings_tmp, liga, especificaciones):
    """especificaciones: lista de (nombre, rating, jugados). Acumula en
    el archivo (varias ligas pueden convivir en el mismo store)."""
    datos = {"equipos": {}}
    if ratings_tmp.exists():
        datos = json.loads(ratings_tmp.read_text(encoding="utf-8"))
    for nombre, rating, jugados in especificaciones:
        llave = f"boot:{liga}|{nombre}"
        datos["equipos"][llave] = {
            "nombre": nombre, "pais": None, "liga": liga,
            "rating": float(rating), "rd": 150.0, "vol": 0.06,
            "partidos_jugados": jugados, "partidos_bootstrap": jugados,
            "partidos_reales": 0, "ultima_actualizacion": "2026-01-01",
        }
    ratings_tmp.write_text(json.dumps(datos), encoding="utf-8")
    return datos["equipos"]


def _leer(ratings_tmp):
    return json.loads(ratings_tmp.read_text(encoding="utf-8"))["equipos"]


def test_calibracion_sube_a_todos_los_equipos_de_la_liga(ratings_tmp):
    base = [(f"Equipo{i}", 1400 + 50 * i, 10) for i in range(6)]
    base.append(("Novato", 1500, 2))          # < minimo_partidos: no cuenta en la media
    base.append(("SinElo", 1550, 10))         # sin par en ClubElo: no cuenta en la media
    _crear_equipos(ratings_tmp, "E0", base)
    _crear_equipos(ratings_tmp, "SP1", [("OtroLiga", 1300, 10)])

    pares = {f"boot:E0|Equipo{i}": float(1400 + 50 * i) + 40.0
             for i in range(6)}               # media = +40
    media = ratings_store.calibrar_liga_a_clubelo("E0", pares)

    assert media == 40.0
    equipos = _leer(ratings_tmp)
    for i in range(6):
        assert equipos[f"boot:E0|Equipo{i}"]["rating"] == 1400 + 50 * i + 40
    assert equipos["boot:E0|Novato"]["rating"] == 1540.0   # 1500 + 40 (se corrige igual)
    assert equipos["boot:E0|SinElo"]["rating"] == 1590.0
    assert equipos["boot:SP1|OtroLiga"]["rating"] == 1300.0  # otra liga intacta


def test_calibracion_dos_veces_no_cambia_lo_segundo(ratings_tmp):
    base = [(f"Equipo{i}", 1400 + 50 * i, 10) for i in range(6)]
    _crear_equipos(ratings_tmp, "E0", base)
    pares = {f"boot:E0|Equipo{i}": float(1400 + 50 * i) + 40.0
             for i in range(6)}

    ratings_store.calibrar_liga_a_clubelo("E0", pares)
    despues_1 = {k: v["rating"] for k, v in _leer(ratings_tmp).items()}
    media_2 = ratings_store.calibrar_liga_a_clubelo("E0", pares)
    despues_2 = {k: v["rating"] for k, v in _leer(ratings_tmp).items()}

    assert abs(media_2) < 0.001
    assert despues_1 == despues_2


def test_menos_equipos_calificados_no_calibra(ratings_tmp):
    base = [(f"Equipo{i}", 1400 + 50 * i, 10) for i in range(5)]  # minimo es 6
    _crear_equipos(ratings_tmp, "E0", base)
    pares = {f"boot:E0|Equipo{i}": 2000.0 for i in range(5)}

    media = ratings_store.calibrar_liga_a_clubelo("E0", pares)

    assert media is None
    equipos = _leer(ratings_tmp)
    for i in range(5):
        assert equipos[f"boot:E0|Equipo{i}"]["rating"] == 1400 + 50 * i


def test_liga_vacia_no_calibra(ratings_tmp):
    _crear_equipos(ratings_tmp, "E0", [])
    assert ratings_store.calibrar_liga_a_clubelo("E0", {}) is None


def test_pares_elo_empareja_por_nombre_y_pais(ratings_tmp):
    filas = [
        {"Club": "Man Red", "Country": "ENG", "Rating": "1800.5"},
        {"Club": "Real Rival", "Country": "ESP", "Rating": "1900"},
        {"Club": "SinRating", "Country": "ENG", "Rating": "abc"},
        {"Country": "ENG", "Rating": "1500"},          # sin Club
        {"Club": "SinPais", "Rating": "1700"},          # sin Country
    ]
    equipos = {
        "boot:E0|Man Red": "Man Red",
        "boot:E0|Club Inexistente Del Cielo": "Club Inexistente Del Cielo",
    }
    pares = pares_elo_desde_ranking(filas, equipos, "E0")
    assert pares == {"boot:E0|Man Red": 1800.5}


def test_pares_elo_sin_match_queda_fuera(ratings_tmp):
    filas = [{"Club": "Man Red", "Country": "ENG", "Rating": "1800"}]
    equipos = {"boot:E0|Zarzaparrilla FC": "Zarzaparrilla FC"}
    assert pares_elo_desde_ranking(filas, equipos, "E0") == {}

"""Tarea 8: la ventaja de local (VENTAJA_LOCAL_ELO, 70) se aplica
tambien al actualizar Glicko-2, solo hacia adelante."""
import json

from poisson_model import VENTAJA_LOCAL_ELO
import cerrar_resultados as C


def _crear_duo(ratings_tmp, neutral=None):
    equipos = {}
    for team_id, nombre in ((1, "Alpha FC"), (2, "Beta FC")):
        equipos[f"espn:{team_id}"] = {
            "nombre": nombre, "pais": None, "liga": "eng.1",
            "rating": 1500.0, "rd": 100.0, "vol": 0.06,
            "partidos_jugados": 10, "partidos_bootstrap": 0,
            "partidos_reales": 10, "ultima_actualizacion": "2026-01-01",
        }
    ratings_tmp.write_text(json.dumps({"equipos": equipos}), encoding="utf-8")
    p = {"home_id": 1, "away_id": 2, "local": "Alpha FC",
         "visitante": "Beta FC"}
    if neutral is not None:
        p["neutral"] = neutral
    return p


def _rating(ratings_tmp, team_id):
    datos = json.loads(ratings_tmp.read_text(encoding="utf-8"))
    return datos["equipos"][f"espn:{team_id}"]["rating"]


def test_local_gana_sube_menos_que_visitante_ganando(ratings_tmp):
    p = _crear_duo(ratings_tmp)
    antes = _rating(ratings_tmp, 1)
    C._actualizar_rating_propio(p, 1, 0)          # gana el local
    subio_local = _rating(ratings_tmp, 1) - antes

    p = _crear_duo(ratings_tmp)                    # store fresco, mismo duelo
    antes = _rating(ratings_tmp, 2)
    C._actualizar_rating_propio(p, 0, 1)          # gana el visitante
    subio_visitante = _rating(ratings_tmp, 2) - antes

    assert subio_local > 0
    assert subio_visitante > 0
    # El rival del local aparece 70 puntos mas debil (y viceversa),
    # asi que ganarle rinde menos.
    assert subio_local < subio_visitante


def test_rival_del_visitante_se_ve_70_puntos_mas_fuerte(ratings_tmp):
    assert VENTAJA_LOCAL_ELO == 70  # se importa, no se duplica

    p = _crear_duo(ratings_tmp)                     # con ajuste
    antes = _rating(ratings_tmp, 2)
    C._actualizar_rating_propio(p, 2, 1)            # pierde el visitante
    caida_con_ajuste = antes - _rating(ratings_tmp, 2)

    p = _crear_duo(ratings_tmp, neutral=True)       # sin ajuste (neutral)
    antes = _rating(ratings_tmp, 2)
    C._actualizar_rating_propio(p, 2, 1)
    caida_sin_ajuste = antes - _rating(ratings_tmp, 2)

    # El rival se ve 70 puntos mas fuerte: perder contra el "fuerte" es
    # menos sorprendente en Glicko, asi que cae MENOS que sin ajuste.
    # (Sin el ajuste ambos escenarios serian identicos.)
    assert caida_con_ajuste < caida_sin_ajuste


def test_sede_neutral_no_se_ajusta(ratings_tmp):
    p = _crear_duo(ratings_tmp, neutral=True)
    antes = _rating(ratings_tmp, 1)
    C._actualizar_rating_propio(p, 1, 0)
    subio_neutral = _rating(ratings_tmp, 1) - antes

    p = _crear_duo(ratings_tmp)                    # mismo duelo, sin neutral
    antes = _rating(ratings_tmp, 1)
    C._actualizar_rating_propio(p, 1, 0)
    subio_con_ventaja = _rating(ratings_tmp, 1) - antes

    # En sede neutral el rival se ve a full (sin -70): gana mas rating.
    assert subio_neutral > subio_con_ventaja

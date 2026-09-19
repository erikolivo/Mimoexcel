"""T3 — Todo tipo emitible por _evaluar_alertas esta en CRITERIO_POR_TIPO (evita B4).

T4 — Mensajes: ambos equipos, escape HTML, reintento si Telegram falla.
"""
import resolucion_alertas as R


TIPOS_EMITIBLES = {
    "tarjeta_roja",
    "alerta_1er_tiempo",
    "posible_victoria_favorito",
    "posible_empate",
    "ampliacion_marcador",
    "gol_de_cierre",
    "cuidado_rival_presiona",
    "value_alert",
    "fav_domina_no_gana",
    "no_fav_domina",
    "siguen_empatados_22",
    "siguen_empatados_55",
    "siguen_empatados_70",
    "cambio_momentum",
}


def test_todos_los_tipos_en_tabla():
    faltantes = [t for t in TIPOS_EMITIBLES if t not in R.CRITERIO_POR_TIPO]
    assert faltantes == []


def test_alias_posible_empate():
    assert R.nombre_normalizado("posible_empate") == "posible_descuento"
    assert R.nombre_normalizado("gol_de_cierre") == "gol_de_cierre"


def _partido():
    return {"local": "Brighton & Hove Albion", "visitante": "Sevilla <FC>",
            "favorito": "Brighton & Hove Albion", "no_favorito": "Sevilla <FC>"}


def _alerta_resuelta():
    return {"tipo": "posible_victoria_favorito", "minuto": "34'", "estado": "acierto",
            "acierto": True, "resuelta_minuto": 41, "resuelta_motivo": "gol_fav"}


def test_mensaje_trae_ambos_equipos():
    txt = R.mensaje_resolucion(_alerta_resuelta(), _partido(), "1-0", "")
    assert "Brighton" in txt and "Sevilla" in txt


def test_mensaje_escapa_html():
    txt = R.mensaje_resolucion(_alerta_resuelta(), _partido(), "1-0", "")
    assert "&amp;" in txt
    assert "& Hove" not in txt and "<FC>" not in txt


def test_mensaje_fallo_y_ambiguo():
    a = _alerta_resuelta()
    a.update(estado="fallo", acierto=False, resuelta_motivo="gol_rival")
    assert "FALLO" in R.mensaje_resolucion(a, _partido(), "0-1", "")
    a.update(estado="ambiguo", acierto=None, resuelta_motivo="ambos_marcaron")
    assert "SIN DETERMINAR" in R.mensaje_resolucion(a, _partido(), "2-1", "")


def test_reintento_si_telegram_falla(monkeypatch):
    import monitor
    partido = {"local": "A", "visitante": "B", "favorito": "A", "no_favorito": "B",
               "alertas_enviadas": []}
    alerta = {"tipo": "gol_de_cierre", "minuto": "78'", "estado": "acierto",
              "acierto": True, "resuelta_minuto": 80, "resuelta_motivo": "gol_fav",
              "resolucion_notificada": False}
    datos = {"partidos": [partido]}
    monkeypatch.setattr(monitor, "enviar_mensaje_telegram", lambda *a, **k: False)
    assert monitor._enviar_resoluciones(partido, datos, [alerta], 1, 0) is False
    assert alerta["resolucion_notificada"] is False
    monkeypatch.setattr(monitor, "enviar_mensaje_telegram", lambda *a, **k: True)
    assert monitor._enviar_resoluciones(partido, datos, [alerta], 1, 0) is True
    assert alerta["resolucion_notificada"] is True

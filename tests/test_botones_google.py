"""Botones de busqueda de las alertas de Telegram.

Los botones deben abrir una busqueda de Google con los equipos como
frases exactas y la fecha LOCAL del partido (UTC-5, la de la hoja).
Sin codificar, un nombre como "Cambrian & Clydach" cortaba la consulta
en el "&" y el boton no encontraba el partido.
"""

import monitor as M


def test_limpia_marcas_y_comillas():
    assert M._limpiar_nombre_busqueda("DC LOCAL ✓") == "DC LOCAL"
    assert M._limpiar_nombre_busqueda("LOCAL ✗") == "LOCAL"
    assert M._limpiar_nombre_busqueda('  Real   "Madrid"  ') == "Real Madrid"
    assert M._limpiar_nombre_busqueda(None) == ""


def test_fecha_local_del_partido():
    # 02:00Z del 1 de noviembre = 21:00 del 31/10 en Ecuador
    assert M._fecha_busqueda({"kickoff_utc": "2026-11-01T02:00:00Z"}) == "31/10/2026"
    assert M._fecha_busqueda({"hora_inicio": "2026-10-31T23:30Z"}) == "31/10/2026"
    assert M._fecha_busqueda({"kickoff_utc": "2026-10-31T12:00:00+00:00"}) == "31/10/2026"
    assert M._fecha_busqueda({}) == ""
    assert M._fecha_busqueda({"kickoff_utc": "sin-fecha"}) == "sin-fecha"


def test_url_codifica_ampersand_comillas_y_fecha():
    url = M._url_google("besoccer.com", "Cambrian & Clydach", "Barry Town", "31/10/2026")
    assert url.startswith("https://www.google.com/search?q=")
    assert "%26" in url                 # el & ya no corta la consulta
    assert "%22" in url                 # frase entre comillas
    assert "31%2F10%2F2026" in url      # la fecha viaja codificada
    assert " " not in url
    assert "# " not in url


def test_url_con_acentos_no_lleva_caracteres_crudos():
    url = M._url_google(None, "Atlético Mineiro", "São Paulo", "31/10/2026")
    assert url.isascii()
    assert "%C3%A9" in url or "%C3%89" in url


def test_teclado_tiene_cuatro_sitios_y_google_general():
    teclado = M._teclado_busqueda({
        "local": "Le Havre AC",
        "visitante": "Paris Saint-Germain",
        "kickoff_utc": "2026-10-31T18:00:00Z",
    })
    filas = teclado["inline_keyboard"]
    botones = [boton for fila in filas for boton in fila]
    assert len(botones) == 5
    assert all(boton["url"].startswith("https://www.google.com/search?q=") for boton in botones)
    assert sum(1 for boton in botones if "site%3A" in boton["url"]) == 4
    general = botones[-1]
    assert "site%3A" not in general["url"]
    assert general["text"] == "🔎 Buscar en Google"
    for boton in botones:
        assert "Le+Havre+AC" in boton["url"]
        assert "Paris+Saint-Germain" in boton["url"] or "Paris+Saint-Germain" in boton["url"].replace("%2D", "-")
        assert "31%2F10%2F2026" in boton["url"]


def test_teclado_usa_la_fecha_local_no_la_utc():
    teclado = M._teclado_busqueda({
        "local": "Colo Colo",
        "visitante": "Universidad de Concepcion",
        "kickoff_utc": "2026-11-01T02:00:00Z",
    })
    url = teclado["inline_keyboard"][0][0]["url"]
    assert "31%2F10%2F2026" in url
    assert "01%2F11%2F2026" not in url

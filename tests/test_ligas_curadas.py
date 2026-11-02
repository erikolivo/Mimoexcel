"""Integridad de LIGAS_ESPN (lista curada de slugs de ESPN).

En noviembre 2026 se audito la lista contra la hoja de favoritos. Estas
pruebas no usan red: solo comprueban que el diccionario mantenga el
formato, que no haya pares pais+liga repetidos, que las etiquetas
corregidas sigan bien y que no vuelvan los slugs que ESPN ya no sirve
(responden 400).
"""

import collections
import re

import fetch_data as F


PATRON_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def test_slugs_con_formato_valido():
    for slug in F.LIGAS_ESPN:
        assert PATRON_SLUG.match(slug), slug
        assert slug == slug.lower()
        assert " " not in slug


def test_cada_entrada_es_pais_y_nombre_no_vacios():
    for slug, valor in F.LIGAS_ESPN.items():
        assert isinstance(valor, tuple), slug
        assert len(valor) == 2, slug
        pais, nombre = valor
        assert isinstance(pais, str) and pais.strip(), slug
        assert isinstance(nombre, str) and nombre.strip(), slug


def test_sin_pais_y_liga_duplicados():
    # Dos slugs distintos no pueden apuntar al mismo pais+liga: seria un
    # error de curado que duplicaria peticiones y etiquetas.
    vistos = collections.Counter(F.LIGAS_ESPN.values())
    repetidos = {par: veces for par, veces in vistos.items() if veces > 1}
    assert repetidos == {}


def test_slugs_muertos_no_vuelven():
    # ESPN responde 400 para estos slugs desde la auditoria de 2026-11.
    muertos = {
        "alg.1", "ang.1", "bel.2", "bul.1", "cro.1", "egy.1", "ger.3",
        "jpn.2", "kaz.1", "kor.1", "kor.2", "mar.1", "pol.1", "pol.2",
        "por.2", "rou.2", "srb.1", "tun.1", "ukr.1",
    }
    assert muertos.isdisjoint(F.LIGAS_ESPN)


def test_etiquetas_corregidas():
    assert F.LIGAS_ESPN["sco.2"] == ("Scotland", "Championship")
    assert F.LIGAS_ESPN["sco.3"] == ("Scotland", "League One")
    assert F.LIGAS_ESPN["den.2"] == ("Denmark", "1. Division")
    assert F.LIGAS_ESPN["bra.1"] == ("Brazil", "Serie A")


def test_ligas_verificadas_presentes():
    esperadas = {
        "eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "bra.1", "arg.1",
        "mex.1", "usa.1", "uefa.champions", "conmebol.libertadores",
        # agregadas en noviembre 2026 con evidencia real
        "arg.copa", "arg.2", "arg.3", "aut.1", "bol.1", "bra.copa_do_brazil",
        "chi.copa_chi", "chn.1", "col.copa", "crc.1", "slv.1",
        "ger.dfb_pokal", "gua.1", "hon.1", "ind.1", "ind.2",
        "ita.coppa_italia", "mex.2", "ned.cup", "por.taca.portugal",
        "sco.cis", "esp.copa_del_rey", "usa.open", "usa.usl.1",
        "usa.usl.l1", "ven.1", "afc.champions", "afc.cup",
        "aff.championship", "caf.nations_qual", "caf.champions",
        "caf.confed", "concacaf.nations.league",
        "concacaf.central.american.cup", "fifa.intercontinental_cup",
        "global.gulf_cup", "uefa.nations", "uefa.euro_u21_qual",
        "uefa.europa.conf", "club.friendly", "fifa.friendly",
    }
    assert esperadas <= set(F.LIGAS_ESPN)


def test_cantidad_minima_de_ligas():
    # La auditoria dejo 107 ligas; una caida grande seria una regresion.
    assert len(F.LIGAS_ESPN) >= 100

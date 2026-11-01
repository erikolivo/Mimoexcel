"""Informe semanal de efectividad: agregados y defensas.

Lee dias archivados de un directorio temporal (nunca data/) y comprueba
los numeros de cada segmento. Sin red.
"""

import datetime
import json

import informe_semanal as I


def _alerta(tipo, acierto):
    return {"tipo": tipo, "acierto": acierto}


def _partido(tipo_pronostico="favorito_directo", prioridad="ALTA", pf=0.80,
             color="ðŸ”µ", clv=0.02, destacado=False, acierto=True, alertas=None):
    return {
        "tipo_pronostico": tipo_pronostico,
        "prioridad": prioridad,
        "pf_hoja": pf,
        "clv": clv,
        "es_destacado": destacado,
        "acierto": acierto,
        "favorito_es_local": True,
        "nivel_actual": {"local": {"poder": 8.0, "color": color}, "visitante": None},
        "alertas_enviadas": alertas or [],
    }


def _escribir(directorio, fecha, partidos):
    (directorio / f"{fecha}.json").write_text(
        json.dumps({"fecha": fecha, "partidos": partidos}, ensure_ascii=False),
        encoding="utf-8",
    )


def _directorio_con_datos(tmp_path, monkeypatch):
    # Ocho dias; solo los dos ultimos llevan alertas detalladas.
    for dia in range(20, 26):
        _escribir(tmp_path, f"2026-10-{dia}", [])

    dia1 = _partido(alertas=[
        _alerta("gol_favorito", True),
        _alerta("gol_favorito", True),
        _alerta("gol_favorito", False),
        _alerta("momento", False),
    ])
    dia2 = _partido(
        tipo_pronostico="doble_oportunidad", prioridad="MEDIA", pf=0.58,
        color="ðŸŸ¡", clv=-0.01, destacado=True, alertas=[
            _alerta("gol_favorito", True),
            _alerta("gol_favorito", False),
            _alerta("valor", True),
            _alerta("valor", None),      # sin resolver: no debe contar
        ])
    _escribir(tmp_path, "2026-10-26", [dia1])
    _escribir(tmp_path, "2026-10-27", [dia2])

    # Un JSON roto no debe romper el informe: se ignora.
    (tmp_path / "2026-10-28.json").write_text("{esto no es json", encoding="utf-8")

    monkeypatch.setattr(I, "HISTORIAL_DIR", tmp_path)
    return tmp_path


def test_informe_global_y_por_tipo(tmp_path, monkeypatch):
    _directorio_con_datos(tmp_path, monkeypatch)
    texto = I.construir_informe(dias=2)
    assert "Efectividad global:</b> 57.1 % (4/7)" in texto
    assert "gol_favorito: 60.0 % (3/5)" in texto
    assert "otros (2 tipos): 50.0 % (1/2)" in texto


def test_informe_por_pick_prioridad_pf_color_y_clv(tmp_path, monkeypatch):
    _directorio_con_datos(tmp_path, monkeypatch)
    texto = I.construir_informe(dias=2)
    assert "favorito directo: 50.0 % (2/4)" in texto
    assert "doble oportunidad: 66.7 % (2/3)" in texto
    assert "ALTA: 50.0 % (2/4)" in texto
    assert "MEDIA: 66.7 % (2/3)" in texto
    assert "75 % o mas: 50.0 % (2/4)" in texto
    assert "55-65 %: 66.7 % (2/3)" in texto
    assert "ðŸ”µ: 50.0 % (2/4)" in texto
    assert "ðŸŸ¡: 66.7 % (2/3)" in texto
    assert "cuota bajo (a favor): 50.0 % (2/4)" in texto
    assert "cuota subio (en contra): 66.7 % (2/3)" in texto
    assert "partidos elegidos: 100.0 % (1/1)" in texto


def test_solo_usa_los_ultimos_dias_pedidos(tmp_path, monkeypatch):
    _directorio_con_datos(tmp_path, monkeypatch)
    texto = I.construir_informe(dias=1)
    assert "2026-10-27 a 2026-10-27" in texto
    assert "57.1 % (4/7)" not in texto
    assert "doble oportunidad: 66.7 % (2/3)" in texto


def test_sin_datos_no_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "HISTORIAL_DIR", tmp_path)
    assert "Todavia no hay dias archivados" in I.construir_informe()


def test_sin_alertas_resueltas(tmp_path, monkeypatch):
    _escribir(tmp_path, "2026-10-27", [_partido(alertas=[_alerta("gol_favorito", None)])])
    monkeypatch.setattr(I, "HISTORIAL_DIR", tmp_path)
    assert "No hay alertas resueltas" in I.construir_informe()


def test_nunca_lanza_si_el_directorio_es_un_archivo(tmp_path, monkeypatch):
    roto = tmp_path / "no_es_carpeta"
    roto.write_text("x", encoding="utf-8")
    monkeypatch.setattr(I, "HISTORIAL_DIR", roto)
    texto = I.construir_informe()
    assert isinstance(texto, str) and texto


def test_buckets():
    assert I._bucket_pf(None) is None
    assert I._bucket_pf(0.54) == "menos de 55 %"
    assert I._bucket_pf(0.55) == "55-65 %"
    assert I._bucket_pf(0.65) == "65-75 %"
    assert I._bucket_pf(0.75) == "75 % o mas"
    assert I._bucket_clv(0.1) == "cuota bajo (a favor)"
    assert I._bucket_clv(0.0) == "sin movimiento"
    assert I._bucket_clv(-0.1) == "cuota subio (en contra)"
    assert I._bucket_clv(None) is None


def test_simular_no_envia(tmp_path, monkeypatch, capsys):
    _directorio_con_datos(tmp_path, monkeypatch)

    def no_enviar(*args, **kwargs):
        raise AssertionError("no deberia enviar en modo simular")

    monkeypatch.setattr(I, "enviar_mensaje_telegram", no_enviar)
    assert I.enviar_informe(dias=2, simular=True) is True
    assert "Informe semanal de alertas" in capsys.readouterr().out


def test_enviar_usa_telegram(tmp_path, monkeypatch):
    _directorio_con_datos(tmp_path, monkeypatch)
    enviados = []
    monkeypatch.setattr(I, "enviar_mensaje_telegram", lambda texto: enviados.append(texto) or True)
    assert I.enviar_informe(dias=2) is True
    assert len(enviados) == 1 and "Efectividad global" in enviados[0]


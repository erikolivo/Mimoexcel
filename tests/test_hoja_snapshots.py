"""Fotos (snapshots) de la hoja: filas EN VIVO, filas ya resueltas y dedupe.

La hoja publicada agrega una fila nueva de cada partido cada vez que corre
(~3,5 por partido y dia). Antes el selector se quedaba con la PRIMERA foto
y ademas podia leer filas EN VIVO o ya marcadas ✓/✗. Aqui se fija el
comportamiento: ultima foto limpia, cuotas de la primera y sin filas vivas.

Sin red y sin escribir en data/.
"""

import datetime

import google_favoritos as G

HOY = datetime.date(2026, 10, 28)


def _csv(filas, con_hora=True):
    hora = "Hora (Ecuador)," if con_hora else ""
    encabezado = (
        "Pais,Liga,Fecha," + hora +
        "Local,% Local,Cuota 1,Cuota X,Cuota 2,% Visitante,Visitante,"
        "Pronostico,Confianza,Prioridad,Fixture ID"
    )
    return encabezado + "\n" + "\n".join(filas) + "\n"


def test_conserva_la_ultima_foto_limpia_y_la_cuota_de_la_primera():
    contenido = _csv([
        "Spain,La Liga,28/10/2026,12:00,Real Madrid,80%,1.25,6.00,11.00,9%,Real Sociedad,LOCAL,***,BAJA,1",
        "Spain,La Liga,28/10/2026,18:00,Real Madrid,82%,1.20,6.50,12.00,8%,Real Sociedad,LOCAL,***,BAJA,1",
    ])
    favoritos = G.interpretar_csv(contenido, hoy=HOY)
    assert len(favoritos) == 1
    unico = favoritos[0]
    assert unico["pct_local"] == 0.82          # la ultima foto
    assert unico["cuota_local"] == 1.20         # la cuota final
    assert unico["cuota_local_primera"] == 1.25  # la de la primera foto
    assert unico["n_fotos"] == 2
    assert unico["fila_hoja"] == 3              # numero de linea en el CSV


def test_ignora_filas_en_vivo_y_marcadas():
    contenido = _csv([
        "Spain,La Liga,28/10/2026,12:00,Real Madrid,80%,1.25,6.00,11.00,9%,Real Sociedad,LOCAL,***,BAJA,1",
        "Spain,La Liga,28/10/2026,EN VIVO,Real Madrid,85%,1.10,8.00,15.00,5%,Real Sociedad,LOCAL ✓,***,BAJA,1",
        "Spain,La Liga,28/10/2026,EN VIVO,Girona,43%,2.35,3.40,2.62,38%,Sevilla,LOCAL,*,ALTA,2",
        "Spain,La Liga,28/10/2026,21:00,Getafe,25%,4.00,4.00,1.62,62%,Betis,VISITANTE ✗,**,ALTA,3",
    ])
    favoritos = G.interpretar_csv(contenido, hoy=HOY)
    assert [f["local"] for f in favoritos] == ["Real Madrid"]
    # La fila EN VIVO ya marcada no cuenta como foto nueva.
    assert favoritos[0]["n_fotos"] == 1
    assert favoritos[0]["cuota_local"] == 1.25


def test_marca_resuelto_detecta_los_cuatro_simbolos():
    assert G._marca_resuelto("LOCAL ✓") is True
    assert G._marca_resuelto("DC LOCAL ✗") is True
    assert G._marca_resuelto("LOCAL ✔") is True
    assert G._marca_resuelto("LOCAL ✘") is True
    assert G._marca_resuelto("DC LOCAL") is False
    assert G._marca_resuelto(None) is False


def test_sin_columna_hora_sigue_leyendo_todo():
    contenido = _csv([
        "Spain,La Liga,28/10/2026,Real Madrid,80%,1.25,6.00,11.00,9%,Real Sociedad,LOCAL,***,BAJA,1",
    ], con_hora=False)
    favoritos = G.interpretar_csv(contenido, hoy=HOY)
    assert len(favoritos) == 1
    assert favoritos[0]["favorito"] == "LOCAL"

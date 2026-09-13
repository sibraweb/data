"""
ARCA / Libro de Sueldos Digital — la tabla oficial de conceptos de sueldo.

⚠ ESTO ES "LA DETERMINACION DEL 931". Juan, 13/09/2026, pidio un recibo de
sueldo de UOCRA para basar los calculos y la determinacion del 931. El Libro de
Sueldos Digital ES el camino por el que hoy se genera el F.931, y ARCA publica
su tabla de conceptos en abierto: codigo, descripcion y a que subsistema aporta
o contribuye cada uno.

Eso convierte la pregunta "como se arma un recibo" en un problema de mapeo
contra una tabla publicada, en vez de una reconstruccion a partir de blogs.

⚠ EL TIPO SE DEDUCE DEL PRIMER DIGITO, Y ESO NO ES UNA SUPOSICION: el PDF
agrupa las filas bajo tres rotulos ("Remunerativos", "No remunerativos",
"Descuentos") que pdfplumber devuelve SUELTOS —a veces en medio de la lista,
porque son celdas rotadas de la columna izquierda—, asi que usar la posicion
del rotulo asignaba mal las filas del borde. Los rangos son explicitos en el
propio documento: 1xxxxx y 499999 remunerativos, 5xxxxx y 799999 no
remunerativos, 8xxxxx descuentos.

⚠ NO HAY CODIGO PARA EL FONDO DE CESE LABORAL, y es un hallazgo, no una falta.
Lo mas cercano es 520010 "Gratificacion por cese laboral" y 520014
"Indemnizacion por despido", que son pagos por TERMINAR la relacion, no el
deposito mensual del 12%/8%. Coincide con la Ley 22.250: el fondo va a una
cuenta a nombre del trabajador (art. 15 y 16) y se prueba con una constancia
mensual escrita propia (art. 29). O sea que es un costo real que NUNCA aparece
en el 931 — quien reconcilie costo de personal contra el 931 va a estar corto
un 12% u 8% y va a creer que le falta plata.

⚠ Y OJO CON EL DESARRAIGO: ARCA lo clasifica REMUNERATIVO (160004 "Adicional
por desarraigo"). Las guias de liquidacion de UOCRA que andan por internet lo
ponen como no remunerativo. Manda esta tabla, que es contra la que valida el
931.

Fuente: https://www.afip.gob.ar/librodesueldosdigital/documentos/nuevos/LSDetalleConceptos.pdf
"""

from __future__ import annotations

import io
import re

import requests

PDF = ("https://www.afip.gob.ar/librodesueldosdigital/documentos/nuevos/"
       "LSDetalleConceptos.pdf")
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Los rangos que el propio PDF declara. El primer digito manda.
TIPOS = {
    "1": "REMUNERATIVO",
    "4": "REMUNERATIVO",      # 499999 Redondeo (Remunerativo)
    "5": "NO_REMUNERATIVO",
    "7": "NO_REMUNERATIVO",   # 799999 Redondeo (No Remunerativo)
    "8": "DESCUENTO",
}

# Los conceptos que hacen falta para liquidar en la construccion, para que la
# pantalla o el modulo puedan pre-seleccionarlos sin que alguien los busque
# entre 120. No es un filtro: la tabla se guarda entera.
RELEVANTES_CONSTRUCCION = {
    "110000",  # Sueldo (el jornal)
    "110007",  # Feriado
    "120003",  # SAC proporcional
    "130001",  # Horas extras al 50 %
    "130002",  # Horas extras al 100 %
    "140000",  # Zona desfavorable
    "160001",  # Adicional por antiguedad
    "160004",  # Adicional por desarraigo  (⚠ REMUNERATIVO segun ARCA)
    "170001",  # Premio por presentismo    (la asistencia perfecta, 20 %)
    "170005",  # Viaticos sin comprobante
    "520003",  # Provision de ropa de trabajo (la "vestimenta" de CAMARCO)
    "810000",  # Sistema previsional   (11 %)
    "810001",  # INSSJyP               (3 %)
    "810002",  # Obra Social           (3 %)
    "810004",  # Cuota Sindical        (2 % UOCRA)
    "810005",  # Seguro de Vida
    "810008",  # Impuesto a las Ganancias
}

_RX_FILA = re.compile(r"^(\d{6})(.+)$")
_RX_RANGO = re.compile(r"^Rango desde (\d{6}) a (\d{6})\s*(.*)$")


def fetch_conceptos() -> list[dict]:
    """Los conceptos publicados, con su tipo y si es de uso libre.

    Devuelve tambien las filas de "Rango desde X a Y", que son los tramos que
    ARCA deja para que el contribuyente numere sus propios conceptos: hacen
    falta para saber DONDE poner uno que la tabla no tiene (por ejemplo la suma
    no remunerativa del acuerdo UOCRA).
    """
    import pdfplumber
    b = requests.get(PDF, timeout=60, headers=HEADERS).content
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)

    filas: list[dict] = []
    vistos: set[str] = set()
    for linea in texto.splitlines():
        linea = linea.strip()
        m = _RX_RANGO.match(linea)
        if m:
            desde, hasta, nota = m.groups()
            filas.append({
                "codigo": desde, "codigo_hasta": hasta,
                "descripcion": re.sub(r"\s+", " ", nota).strip(),
                "tipo": TIPOS.get(desde[0], ""),
                "uso_libre": "SI", "relevante_construccion": "",
            })
            continue
        m = _RX_FILA.match(linea)
        if not m:
            continue
        codigo, desc = m.groups()
        if codigo in vistos or codigo[0] not in TIPOS:
            continue
        vistos.add(codigo)
        filas.append({
            "codigo": codigo, "codigo_hasta": "",
            "descripcion": re.sub(r"\s+", " ", desc).strip(),
            "tipo": TIPOS[codigo[0]],
            "uso_libre": "",
            "relevante_construccion": "SI" if codigo in RELEVANTES_CONSTRUCCION else "",
        })
    return filas


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    cs = fetch_conceptos()
    print("%s conceptos" % len(cs))
    for t in ("REMUNERATIVO", "NO_REMUNERATIVO", "DESCUENTO"):
        n = sum(1 for c in cs if c["tipo"] == t)
        print("   %-18s %3d" % (t, n))
    print("\n== los que hacen falta para liquidar en construccion ==")
    for c in cs:
        if c["relevante_construccion"]:
            print("   %-8s %-18s %s" % (c["codigo"], c["tipo"], c["descripcion"][:58]))
    faltan = RELEVANTES_CONSTRUCCION - {c["codigo"] for c in cs}
    if faltan:
        print("\n   ⚠ codigos esperados que NO aparecieron: %s" % sorted(faltan))

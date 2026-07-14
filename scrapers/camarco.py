"""
CAMARCO / Índice CAC — "Indicador de la Variación del Costo de un Edificio
Tipo en Capital Federal".

La fuente oficial (camarco.org.ar) tiene el reporte completo detrás de un
login de socios — solo el número del mes corriente es público. En cambio
cifrasonline.com.ar (consultora privada) republica la serie histórica
completa en un Excel público, sin login: se usa esa como fuente.

OJO: la URL incluye el año de la última actualización del archivo
("...-2024-actualizada.xls") — cifrasonline sube un archivo nuevo con año
distinto cuando actualizan la serie, no es una URL fija para siempre.
Si en el futuro esto empieza a devolver 404, hay que volver a
https://www.cifrasonline.com.ar/indice-cac/ y tomar el link vigente.
"""

from __future__ import annotations

import datetime as dt

import requests
import xlrd

URL = (
    "https://www.cifrasonline.com.ar/wp-content/uploads/2025/01/"
    "Indicador-CAC_serie-historica-2024-actualizada.xls"
)

DENOMINACIONES = {
    "Costo de Construcción": "COSTO_CONSTRUCCION",
    "Materiales": "MATERIALES",
    "Mano de Obra": "MANO_DE_OBRA",
}


def _serial_a_fecha(n) -> str | None:
    if not isinstance(n, (int, float)) or not n:
        return None
    try:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(n))).isoformat()
    except (OverflowError, ValueError):
        return None


def fetch_cac() -> list[dict]:
    """Devuelve una fila por período: {FECHA, COSTO_CONSTRUCCION, MATERIALES, MANO_DE_OBRA}
    (índice base 100 = dic-2014).

    El archivo trae los datos en tríos de filas por período — "Costo de
    Construcción", "Materiales", "Mano de Obra" — y la fecha (serial Excel)
    solo aparece en la fila del medio ("Materiales"). Por eso se agrupa de
    a 3 filas en vez de ir arrastrando la última fecha vista fila a fila
    (si no, la fila "Costo de Construcción" queda mal atribuida al período
    anterior, porque aparece ANTES que la fila con la fecha)."""
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_name("CAC")

    # Detectar la primera fila de datos: la primera cuyo valor de DENOMINACIÓN
    # (columna 3) sea "Costo de Construcción".
    inicio = next(
        row for row in range(ws.nrows)
        if str(ws.row_values(row)[3]).strip() == "Costo de Construcción"
    )

    filas = []
    for row in range(inicio, ws.nrows - 2, 3):
        trio = [ws.row_values(row + i) for i in range(3)]
        fecha = next((_serial_a_fecha(t[1]) for t in trio if _serial_a_fecha(t[1])), None)
        if fecha is None:
            continue
        fila = {"FECHA": fecha}
        for t in trio:
            col = DENOMINACIONES.get(str(t[3]).strip())
            if col and isinstance(t[5], (int, float)):
                fila[col] = t[5]
        filas.append(fila)

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_cac()
    print(f"CAC: {len(serie)} períodos, último: {serie[-1] if serie else None}")

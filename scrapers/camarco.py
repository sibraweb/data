"""
CAMARCO / Índice CAC — "Indicador de la Variación del Costo de un Edificio
Tipo en Capital Federal".

La fuente oficial (camarco.org.ar) tiene el reporte completo detrás de un
login de socios — solo el número del mes corriente es público. cifrasonline.com.ar
(consultora privada) republica la serie histórica completa, pero el Excel
que se descarga desde la página (`.../uploads/2025/01/...-2024-actualizada.xls`)
quedó DISCONTINUADO en dic-2024 — desde entonces solo actualizan el reporte
del mes corriente vía una revista digital (Issuu, no scrapeable de forma
confiable).

Se encontró la fuente real que SÍ sigue viva: la página tiene un botón
"Años anteriores" que en realidad apunta a un **Google Sheets público**
(no hace falta OAuth, es de lectura libre vía export CSV) que cifrasonline
actualiza junto con cada informe mensual — llega hasta el mes más reciente
(marcado "(*)" mientras es provisorio). Si en el futuro esto empieza a
fallar, volver a https://www.cifrasonline.com.ar/indice-cac/ y revisar el
link "Años anteriores" (puede cambiar de ID de documento).
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import re

import requests

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/1vwNajGnxY3rcg-5ogkVpKfTVSjALyzLL/export?format=csv"
)

DENOMINACIONES = {
    "Costo de Construcción": "COSTO_CONSTRUCCION",
    "Materiales": "MATERIALES",
    "Mano de Obra": "MANO_DE_OBRA",
}

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _periodo_a_fecha(periodo: str) -> str | None:
    """'mar-26' -> último día del mes ('2026-03-31') — mismo criterio de
    "fecha vigente a fin de mes" que el resto del proyecto.
    OJO: setiembre está abreviado "sept" (4 letras) en vez de "sep" (3,
    como el resto de los meses) — se toman las primeras 3 letras nomás."""
    m = re.match(r"^([a-zA-Z]{3,4})-(\d{2})$", periodo.strip())
    if not m:
        return None
    mes = MESES.get(m.group(1).lower()[:3])
    if not mes:
        return None
    anio = 2000 + int(m.group(2))
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return dt.date(anio, mes, ultimo_dia).isoformat()


def _numero_ar(valor: str) -> float | None:
    """'22.204,20' -> 22204.20 (formato argentino: punto de miles, coma decimal)."""
    valor = valor.strip()
    if not valor:
        return None
    try:
        return float(valor.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def fetch_cac() -> list[dict]:
    """Devuelve una fila por período: {FECHA, COSTO_CONSTRUCCION, MATERIALES, MANO_DE_OBRA}
    (índice base 100 = dic-2014).

    La hoja trae los datos en tríos de filas por período — "Costo de
    Construcción", "Materiales", "Mano de Obra" — y el período (ej. "mar-26")
    solo aparece en la fila del medio ("Materiales"). Por eso se agrupa de a
    3 filas en vez de ir arrastrando el último período visto fila a fila (si
    no, la fila "Costo de Construcción" queda mal atribuida al período
    anterior, porque aparece ANTES que la fila con el período).

    OJO: `sheets.upsert_series` solo AGREGA filas con una clave (FECHA) nueva
    — no actualiza una fila ya guardada. Los últimos 1-2 meses vienen
    marcados "(*)" (provisorios) y cifrasonline los puede revisar más
    adelante; si eso pasa, el valor viejo queda guardado hasta que alguien
    lo borre a mano de la hoja CAC."""
    r = requests.get(SHEET_CSV_URL, timeout=30)
    r.raise_for_status()
    filas_csv = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))

    inicio = next(
        i for i, row in enumerate(filas_csv)
        if len(row) > 3 and row[3].strip() == "Costo de Construcción"
    )

    filas = []
    for i in range(inicio, len(filas_csv) - 2, 3):
        trio = filas_csv[i:i + 3]
        if any(len(t) <= 5 for t in trio):
            break
        denominaciones_trio = {t[3].strip() for t in trio}
        if not denominaciones_trio & set(DENOMINACIONES):
            break  # se acabó la tabla de datos (notas al pie del documento)

        fecha = next((_periodo_a_fecha(t[1]) for t in trio if t[1].strip()), None)
        if fecha is None:
            continue

        fila = {"FECHA": fecha}
        for t in trio:
            col = DENOMINACIONES.get(t[3].strip())
            if col:
                valor = _numero_ar(t[5])
                if valor is not None:
                    fila[col] = valor
        filas.append(fila)

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_cac()
    print(f"CAC: {len(serie)} períodos, último: {serie[-1] if serie else None}")

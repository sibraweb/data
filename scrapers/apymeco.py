"""
APYMECO — indice de la construccion y costo por m2.

⚠ POR QUE ESTE SCRAPER NO EXISTIA Y LA SERIE IGUAL ESTABA. `CONSTRUCCION` se
cargo UNA VEZ desde un Excel (`CONST_2.xlsx`, ver `api/migrar_historico.py`) y
nunca tuvo quien la actualice: no habia scraper ni entrada en la cadena. Por eso
estaba parada en feb-2026 con 197 dias de atraso — no era un job que falla, era
que el job no existia. Y mientras tanto el indice seguia ofreciendose como
pactable en `/api/redet/series`, asi que se podia firmar un contrato contra algo
que nadie actualizaba.

Fuente: https://www.apymeco.com.ar/indice.php (la paso Juan, 13/09/2026).

⚠ LA PAGINA TRAE UN SOLO INDICE, NO LOS CUATRO. El Excel historico tenia
INDICE_GENERAL, MATERIALES, MANO_DE_OBRA y PROVISIONES; la pagina publica solo
el general y el $/m2. Asi que este scraper actualiza esas dos columnas y **las
otras tres quedan en NULL para los meses nuevos**. Eso es a proposito: NULL dice
"aca no se publica", y rellenarlas con el ultimo valor conocido fabricaria una
apertura que nadie publico. Los cuatro valores viejos quedan como estan.

⚠ Los PDF del "informe mensual" NO sirven: sus URLs viven en `_temp/` con
nombres de sesion y contestan 404 apenas se reusan (probado el 13/09/2026). Si
algun dia hace falta la apertura, hay que pedirsela a APYMECO.

⚠ LA PAGINA MUESTRA 13 MESES, no el historico. Como los topes de ARCA, esto
acumula: cada corrida agrega los meses nuevos y no toca los viejos (el upsert
del proyecto es append-only a proposito, ver PROCESO.md).

⚠ DOS FORMAS DE ESCRIBIR EL MES EN LA MISMA TABLA: "AGO/26" y "AGO/2025"
conviven, y setiembre va como "SET". Exigir un solo formato perdia filas.
"""

from __future__ import annotations

import calendar
import datetime as dt
import html
import re

import requests

URL = "https://www.apymeco.com.ar/indice.php"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


def _texto(x: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()


def _plata(x: str) -> float | None:
    """"$ 2.383.862,97" -> 2383862.97 · "15.748,17" -> 15748.17 · "10880,96" -> 10880.96.

    ⚠ LA PARTE ENTERA NO SE LIMITA A TRES DIGITOS. Primero puse
    `\\d{1,3}(?:\\.\\d{3})*`, que es correcto para la WEB (escribe "15.748,17"
    con punto de miles) y corrompe el PDF (escribe "10880,96" sin punto):
    agarraba "108" y devolvia 108,00 en vez de 10.880,96. Los cargo y los vi
    imprimir 821,00 donde la base decia 8.212,91 — un error que no revienta,
    solo miente por un factor de diez.
    """
    m = re.search(r"(\d+(?:\.\d{3})*(?:,\d+)?)", x or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _fin_de_mes(anio: int, mes: int) -> str:
    """Fin de mes, igual que el resto del proyecto (CAC, ICC, IPC)."""
    return dt.date(anio, mes, calendar.monthrange(anio, mes)[1]).isoformat()


def fetch_apymeco() -> list[dict]:
    """Una fila por mes: {FECHA, INDICE_GENERAL, PESOS_M2, VARIACION_MENSUAL}.

    ⚠ NO devuelve MATERIALES / MANO_DE_OBRA / PROVISIONES: la pagina no los
    publica. Ver la nota de arriba.
    """
    r = requests.get(URL, timeout=45, headers=HEADERS)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"

    filas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I):
        celdas = [_texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        celdas = [c for c in celdas if c]
        if len(celdas) < 3:
            continue
        m = re.fullmatch(r"([A-Z]{3})\s*/\s*(\d{2}|\d{4})", celdas[0].upper())
        if not m:
            continue
        mes = MESES.get(m.group(1))
        if not mes:
            continue
        crudo = m.group(2)
        anio = int(crudo) if len(crudo) == 4 else 2000 + int(crudo)
        filas.append({
            "FECHA": _fin_de_mes(anio, mes),
            "PESOS_M2": _plata(celdas[1]),
            "INDICE_GENERAL": _plata(celdas[2]),
            "VARIACION_MENSUAL": _plata(celdas[3]) if len(celdas) > 3 else None,
        })
    return sorted(filas, key=lambda f: f["FECHA"])


def fetch_apymeco_pdf(ruta: str) -> list[dict]:
    """El histórico COMPLETO con las cuatro columnas, del informe mensual en PDF.

    ⚠ ESTO ES LO QUE LA PAGINA NO DA. `fetch_apymeco()` saca de la web el indice
    general y el $/m2 de los ultimos 13 meses; el PDF trae la tabla "Resumen
    indice" con MANO DE OBRA, MATERIALES, PROVISIONES DE 3ROS y el APYMECO
    general desde oct-2015. Juan pasa el informe cada tanto (13/09/2026).

    ⚠ EL ORDEN DE COLUMNAS NO SE ADIVINA: SE VERIFICO. El encabezado sale
    desarmado de pdfplumber (el texto envuelve en tres lineas), asi que el orden
    se confirmo contra nuestra propia base, que ya tenia feb-2026 cargado del
    Excel historico:
        PDF  feb-26   8366,27   19967,93   25235,62   13397,49
        base feb-26   MANO_DE_OBRA · MATERIALES · PROVISIONES · GENERAL
    Coinciden los cuatro. Si en un informe futuro el orden cambiara, el control
    de `--verificar` lo delata en vez de cargar los valores cruzados.

    ⚠ SETIEMBRE VA CON CUATRO LETRAS ("sept-25") y el resto con tres. Es el
    mismo detalle que ya habia mordido en la planilla del CAC.
    """
    import pdfplumber
    filas = []
    with pdfplumber.open(ruta) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    rx = re.compile(
        r"^\s*([a-z]{3,4})-(\d{2})\s+"
        r"([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$")
    for linea in texto.splitlines():
        m = rx.match(linea)
        if not m:
            continue
        mes = MESES.get(m.group(1)[:3].upper())
        if not mes:
            continue
        filas.append({
            "FECHA": _fin_de_mes(2000 + int(m.group(2)), mes),
            "MANO_DE_OBRA": _plata(m.group(3)),
            "MATERIALES": _plata(m.group(4)),
            "PROVISIONES": _plata(m.group(5)),
            "INDICE_GENERAL": _plata(m.group(6)),
        })
    # ⚠ UN MES REPETIDO CON OTROS VALORES ES UN ERROR DEL INFORME, Y SE AVISA.
    # Antes hacia `unicos[fecha] = f` y se quedaba con el ultimo, en silencio.
    # Eso TAPO un error real: el informe de nov-2021 escribe "jul-19" dos veces
    # —la segunda son los valores de jul-20— y APYMECO lo corrigio para el
    # informe de ago-2026. Con el dedup mudo, esa fila entraba como jul-2019 con
    # los numeros de 2020 y parecia que la camara habia revisado su serie.
    # Ahora se descarta la repetida y se imprime, porque un mes duplicado quiere
    # decir que hay una etiqueta mal y la fila siguiente tambien puede estar
    # corrida.
    unicos: dict[str, dict] = {}
    repetidos = []
    for f in filas:
        previo = unicos.get(f["FECHA"])
        if previo is None:
            unicos[f["FECHA"]] = f
            continue
        distinto = any(abs((previo.get(c) or 0) - (f.get(c) or 0)) > 0.01
                       for c in ("MANO_DE_OBRA", "MATERIALES", "PROVISIONES",
                                 "INDICE_GENERAL"))
        if distinto:
            repetidos.append((f["FECHA"], previo, f))
    for fecha, a, b in repetidos:
        print("   ⚠ %s aparece dos veces con valores distintos en el informe. "
              "Se toma la PRIMERA (%.2f) y se descarta (%.2f). Hay una etiqueta "
              "de mes mal en el PDF."
              % (fecha, a.get("INDICE_GENERAL") or 0, b.get("INDICE_GENERAL") or 0))
    return [unicos[k] for k in sorted(unicos)]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    pdfs = [a for a in sys.argv[1:] if a.lower().endswith(".pdf")]
    if pdfs:
        fs = fetch_apymeco_pdf(pdfs[0])
        print("%d meses del PDF: %s -> %s\n" % (len(fs), fs[0]["FECHA"], fs[-1]["FECHA"]))
        for f in fs[-8:]:
            print("   %s   m.obra %10.2f   materiales %10.2f   provisiones %10.2f   GENERAL %10.2f"
                  % (f["FECHA"], f["MANO_DE_OBRA"], f["MATERIALES"],
                     f["PROVISIONES"], f["INDICE_GENERAL"]))
        raise SystemExit(0)
    fs = fetch_apymeco()
    print("%d meses leidos%s" % (len(fs), (": %s -> %s" % (fs[0]["FECHA"], fs[-1]["FECHA"])) if fs else ""))
    for f in fs:
        print("   %s   indice %12s   $/m2 %16s   var %6s %%"
              % (f["FECHA"],
                 ("%.2f" % f["INDICE_GENERAL"]) if f["INDICE_GENERAL"] else "-",
                 ("%.2f" % f["PESOS_M2"]) if f["PESOS_M2"] else "-",
                 ("%.2f" % f["VARIACION_MENSUAL"]) if f["VARIACION_MENSUAL"] is not None else "-"))

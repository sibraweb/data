"""
CAMARCO / seccion laboral — los acuerdos salariales con su FECHA.

⚠ PARA QUE SIRVE. Juan, 13/09/2026: *«podriamos saber la fecha de cuando se
publica las nuevas actualizaciones de uocra, por ejemplo el valor de octubre se
supo el 19 de agosto»*. Ni la escala de uocra.org ni la API de iKiwi traen esa
fecha: la pagina de UOCRA etiqueta los PDFs por el PERIODO que rigen ("junio,
julio y agosto"), no por cuando salieron. El feed de CAMARCO si: es WordPress y
cada entrada tiene su `date` de publicacion.

⚠ Y HAY DOS FECHAS DISTINTAS QUE NO SON LA MISMA COSA:
  · `FECHA_PUBLICACION` — cuando CAMARCO lo subio. La sabemos siempre.
  · `FECHA_SUSCRIPCION` — cuando las partes lo firmaron, que esta DENTRO del
    PDF ("a los 19 dias del mes de agosto de 2026"). Es la que Juan recuerda y
    la que importa: es el dia en que el numero se pudo saber.
La de homologacion es una tercera y aparece en las entradas que la anuncian.

⚠ LOS PERIODOS SALEN DEL TITULO, TRANSCRITOS. "Acuerdo Salarial UOCRA CCT N°
76/75 Junio - Julio - Agosto 2026" da tres meses. Si el titulo no los nombra,
la lista va vacia: no se deduce el periodo por la fecha de publicacion, porque
el mismo feed tiene actas complementarias que corrigen un acuerdo viejo y
adivinar ahi produciria un mes equivocado con cara de dato.

⚠ EL CERTIFICADO DE camarco.org.ar NO VALIDA en esta maquina — igual que el de
api.bcra.gob.ar. Va `verify=False`, misma decision ya tomada y documentada en
`api/cargar_camarco_certificados.py` y `scrapers/bcra.py`.
"""

from __future__ import annotations

import html
import io
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API = "https://www.camarco.org.ar/wp-json/wp/v2/laboral"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Los convenios que aparecen en el feed. Solo el 76/75 y el 577/10 son los de
# Juan (obra privada y obra publica); los demas son otros sectores y se
# guardan igual para no tener que volver a scrapear si algun dia hacen falta.
CONVENIOS = ["76/75", "577/10", "545/08", "660/13", "735/15", "200/75", "445/06"]


def _limpio(x: str) -> str:
    x = html.unescape(re.sub(r"<[^>]+>", " ", x or ""))
    return re.sub(r"\s+", " ", x).strip()


def _periodos_del_titulo(titulo: str) -> list[str]:
    """Los meses que el titulo nombra, como "2026-06". Transcritos, no deducidos."""
    t = titulo.lower()
    # el anio del titulo: el ultimo de 4 digitos que aparezca
    anios = re.findall(r"\b(20\d{2})\b", t)
    if not anios:
        return []
    anio = int(anios[-1])
    vistos, out = set(), []
    # ⚠ se recorre EN EL ORDEN DEL TEXTO y no en el del diccionario: un titulo
    # "Diciembre 2025 - Enero 2026" nombra dos anios y el orden importa para
    # saber cual mes cae en cual.
    for m in re.finditer(r"|".join(MESES), t):
        nombre = m.group()
        num = MESES[nombre]
        if num in vistos:
            continue
        vistos.add(num)
        out.append("%04d-%02d" % (anio, num))
    # si el titulo cruza de anio (dic + ene), el diciembre es del anterior
    nums = [int(p[5:]) for p in out]
    if nums and max(nums) == 12 and min(nums) <= 2:
        out = ["%04d-%02d" % (anio - 1 if int(p[5:]) == 12 else anio, int(p[5:]))
               for p in out]
    return sorted(out)


def _tipo(titulo: str) -> str:
    t = titulo.lower()
    if t.startswith("homologaci") or "homologaci" in t.split("acuerdo")[0]:
        return "homologacion"
    if "acta complementaria" in t:
        return "acta"
    if "homologaci" in t:
        return "homologacion"
    return "acuerdo"


# La formula de encabezado de un acta: "a los 19 dias del mes de agosto de 2026".
#
# ⚠ HUBO UN SEGUNDO PATRON Y ESTABA MAL. Probe tambien "fecha N de MES de AAAA"
# como respaldo, y devolvio 1988-02-16 para dos homologaciones de 2026: eso sale
# de "el Decreto N° 200 de fecha 16 de febrero de 1988", que es una CITA LEGAL
# dentro del considerando. Esa redaccion es justamente como se citan los
# decretos, asi que era una mala senal y se saco. Queda solo la formula del
# encabezado, que es la del propio documento.
_RX_SUSCRIPCION = re.compile(
    r"a\s+los?\s+(\d{1,2})\s+d[ií]as?\s+del\s+mes\s+de\s+(%s)\s+(?:de\s+)?(\d{4})"
    % "|".join(MESES), re.I)

# Un acuerdo se firma ANTES de publicarse, de dias a semanas — nunca anios.
# Sirve de guardia contra una cita legal que se colo: si la fecha leida cae
# fuera de esta ventana, no es la del documento y se devuelve None.
DIAS_ANTES_MAX = 400
DIAS_DESPUES_MAX = 5


def fecha_suscripcion_del_pdf(url: str, publicado: str | None = None,
                              timeout: int = 60) -> str | None:
    """La fecha de firma que esta DENTRO del PDF, o None si no se lee.

    ⚠ NO SE INVENTA: si el PDF es una imagen escaneada, si la formula esta
    escrita de otra manera, o si la fecha leida no es plausible contra la de
    publicacion, devuelve None. La regla de la casa es que los bots transcriben
    y no deducen; poner aca la fecha de publicacion como si fuera la de firma
    seria exactamente el error que esa regla previene.
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        b = requests.get(url, timeout=timeout, headers=HEADERS, verify=False).content
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            texto = " ".join((p.extract_text() or "") for p in pdf.pages[:3])
    except Exception:
        return None
    m = _RX_SUSCRIPCION.search(re.sub(r"\s+", " ", texto))
    if not m:
        return None
    fecha = "%s-%02d-%02d" % (m.group(3), MESES[m.group(2).lower()], int(m.group(1)))
    if publicado:
        try:
            import datetime as dt
            f = dt.date.fromisoformat(fecha)
            p = dt.date.fromisoformat(publicado)
            if not (p - dt.timedelta(days=DIAS_ANTES_MAX) <= f
                    <= p + dt.timedelta(days=DIAS_DESPUES_MAX)):
                return None
        except ValueError:
            return None
    return fecha


def fetch_acuerdos(paginas: int = 4, con_pdf: int = 0) -> list[dict]:
    """Los acuerdos del feed laboral, del mas nuevo al mas viejo.

    `paginas`: de 25 entradas cada una.
    `con_pdf`: a cuantas de las MAS RECIENTES abrirles el PDF para sacar la
        fecha de suscripcion. 0 = ninguna (rapido). Cada PDF es una descarga,
        asi que no se abren los 100 por defecto.
    """
    filas: list[dict] = []
    for pagina in range(1, paginas + 1):
        r = requests.get(f"{API}?per_page=25&page={pagina}&orderby=date&order=desc",
                         timeout=45, headers=HEADERS, verify=False)
        if r.status_code != 200:
            break
        datos = r.json()
        if not isinstance(datos, list) or not datos:
            break
        for p in datos:
            titulo = _limpio(p.get("title", {}).get("rendered", ""))
            crudo = p.get("content", {}).get("rendered", "") or ""
            pdfs = list(dict.fromkeys(re.findall(r"https?://[^\s\"'<>]+\.pdf", crudo)))
            filas.append({
                # el slug es estable y unico; el titulo lo pueden editar
                "CLAVE": (p.get("slug") or "")[:200],
                "TITULO": titulo,
                "FECHA_PUBLICACION": (p.get("date") or "")[:10],
                "TIPO": _tipo(titulo),
                "CONVENIOS": [c for c in CONVENIOS if c in titulo],
                "PERIODOS": _periodos_del_titulo(titulo),
                "LINK": p.get("link"),
                "PDFS": pdfs,
                "FECHA_SUSCRIPCION": None,
            })
        if len(datos) < 25:
            break

    for f in filas[:con_pdf]:
        for u in f["PDFS"]:
            fecha = fecha_suscripcion_del_pdf(u, publicado=f["FECHA_PUBLICACION"])
            if fecha:
                f["FECHA_SUSCRIPCION"] = fecha
                break
    return filas


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    acs = fetch_acuerdos(paginas=4, con_pdf=n)
    print(f"{len(acs)} entradas (PDF abierto a las {n} mas recientes)\n")
    for a in acs[:24]:
        print("pub %s  firmado %-10s  %-12s %-16s %s"
              % (a["FECHA_PUBLICACION"], a["FECHA_SUSCRIPCION"] or "-",
                 a["TIPO"], ",".join(a["CONVENIOS"]) or "-",
                 ",".join(a["PERIODOS"]) or "(sin periodo en el titulo)"))
        print("     %s" % a["TITULO"][:96])

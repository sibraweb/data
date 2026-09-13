"""
CAMARCO / Incidencia de las cargas sociales sobre la mano de obra directa.

⚠ ESTO ES EL 2,15. Juan, 13/09/2026: *«podes ver algun lugar que publique como
se liquida el sueldo del personal obrero, que entonces podamos saber cada mes
cuanto termina siendo por sobre uocra, en vez de hacer siempre 2,15, ya que se
considera ropa y demas ahi»*. CAMARCO lo publica: el "Trabajo Tecnico Nº 185"
(vigencia 1º/07/2026) da un coeficiente de 213,50% DESAGREGADO en diez items,
y uno de ellos es literalmente "Asignacion para vestimenta" (3,61%).

⚠ LA PAGINA LO TAPA, LA API DE MEDIOS NO. El indicador en la web dice "This
section is only available to registered users", pero los PDF estan publicados
en `wp-json/wp/v2/media`. Mismo patron que ya resolvio el descuento de
certificados (ver METODOLOGIA__DESCUENTO_CERTIFICADOS.md): el login que
parecia infranqueable no hacia falta.

⚠ SE LEE EL RESUMEN, NO EL TRABAJO COMPLETO. Cada publicacion sube tres PDF:
la nota circular (una pagina, trae el coeficiente nuevo y el anterior), el
RESUMEN (una pagina, la tabla de diez items) y el trabajo completo (8 paginas
de memoria de calculo). La tabla sale del RESUMEN porque es la que esta
tabulada; del completo no se extrae nada automatico.

⚠ DOS SERIES DISTINTAS Y NO SE MEZCLAN: "Mano de Obra Directa" (obreros) y
"Capataces", que son trabajos separados con vigencias distintas.

⚠ Y OJO CON EL ITEM DE ART. CAMARCO usa el PROMEDIO PAIS de la cuota pactada
que releva la Superintendencia de Riesgos del Trabajo (5,8% de la masa salarial
a marzo 2026), y el propio PDF avisa que "existe para esta Carga Social una
dispersion muy grande entre una empresa y otra". Para un modulo de mano de obra
PROPIA ese item se reemplaza por la alicuota real de la empresa; los otros
nueve sirven tal cual. Por eso se guarda item por item y no solo el total.

⚠ El certificado de camarco.org.ar no valida en esta maquina: `verify=False`,
misma decision ya documentada en `api/cargar_camarco_certificados.py`.
"""

from __future__ import annotations

import io
import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MEDIA = ("https://www.camarco.org.ar/wp-json/wp/v2/media"
         "?search=Cargas%20Sociales&per_page=100&orderby=date&order=desc")
HEADERS = {"User-Agent": "Mozilla/5.0"}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# ⚠ EL CONCEPTO SE TRANSCRIBE, NO SE ASUME. Primero tuve un diccionario con
# los diez renglones de obreros (a..j) y los capataces no entraban: su resumen
# tiene SIETE items (a..g) y otros conceptos —"Sueldo por tiempo corrido" en
# vez de "Salario por tiempo efectivamente trabajado", sin asistencia perfecta
# ni vestimenta, total 148,85% contra 213,50%—. Asumir la grilla de un grupo
# descartaba el otro en silencio. Ahora se lee la letra, el texto tal cual y el
# numero; la grilla de abajo queda solo para reconocer los acumuladores.
#
# Un renglon cuyo texto diga "subtotal" o "costo total" es un CONTROL, no un
# sumando: sumarlo duplicaria todo. Se detecta por el texto leido, que es lo
# que el PDF dice, y no por la posicion de la letra (en obreros el subtotal es
# la "g" y en capataces la "d").
ACUMULADOR_SUBTOTAL = "subtotal"
ACUMULADOR_TOTAL = "costo total"


def _clase_del_item(concepto: str) -> str:
    c = concepto.lower()
    if ACUMULADOR_TOTAL in c:
        return "total"
    if ACUMULADOR_SUBTOTAL in c:
        return "subtotal"
    return "sumando"


_RX_VIGENCIA = re.compile(
    r"VIGENCIA\s+(\d{1,2})\s*º?\s*de\s+(%s)\s+de\s+(\d{4})" % "|".join(MESES), re.I)
_RX_TRABAJO = re.compile(r"Trabajo\s+(?:T[eé]cnico\s+)?N[º°]\s*(\d{2,4})", re.I)
# ⚠ el signo de porcentaje va DOBLADO: el patron se arma con `%` de Python y
# un `%?` suelto revienta con "unsupported format character '?'".
_RX_CUOTA_ART = re.compile(
    r"asciende\s+al\s+([\d.,]+)\s*%%?\s*,?\s*para\s+el\s+mes\s+de\s+(%s)\s+(\d{4})"
    % "|".join(MESES), re.I)


def _pct(x: str) -> float:
    """"166,45" -> 166.45. La fuente usa coma decimal y a veces punto."""
    x = x.strip().replace(" ", "")
    if "," in x:
        x = x.replace(".", "").replace(",", ".")
    return float(x)


def _grupo_del_nombre(url: str) -> str | None:
    u = url.lower()
    if "capataces" in u:
        return "CAPATACES"
    if "mano-de-obra" in u or "mod-trab" in u:
        return "MANO_DE_OBRA_DIRECTA"
    return None


def parsear_resumen(texto: str) -> dict | None:
    """La tabla de diez items de un PDF de RESUMEN.

    Devuelve None si el texto no es un resumen (no trae VIGENCIA ni la tabla).
    No adivina: un item que no se lee queda fuera y el control de suma lo
    delata, en vez de rellenarse con el del trabajo anterior.
    """
    t = re.sub(r"[ \t]+", " ", texto)
    m_vig = _RX_VIGENCIA.search(t)
    if not m_vig:
        return None
    vigencia = "%s-%02d-%02d" % (m_vig.group(3), MESES[m_vig.group(2).lower()],
                                 int(m_vig.group(1)))

    # cada renglon: la letra sola, el concepto, y el porcentaje al final.
    # ⚠ el numero se ancla AL FINAL DE LINEA porque el concepto de la fila "c"
    # trae la marca de nota "(1)" en el medio y un `\d+` suelto la agarraba.
    items: list[dict] = []
    vistas: set[str] = set()
    lineas = t.splitlines()
    _es_item = re.compile(r"\s*[a-z]\s+.*[\d]{1,3}[.,]\d{2}\s*$")
    for n, linea in enumerate(lineas):
        m = re.match(r"\s*([a-z])\s+(?!\d)(.+?)([\d]{1,3}[.,]\d{2})\s*$", linea)
        if not m:
            continue
        letra = m.group(1).lower()
        if letra in vistas:
            continue
        concepto = re.sub(r"\s*\(\d\)\s*$", "", m.group(2).strip())
        if not concepto:
            # ⚠ EL RENGLON PARTIDO EN TRES. El item "c" de obreros tiene el
            # concepto tan largo que el PDF lo envuelve y deja la letra sola
            # con la marca de nota:
            #     Salarios pagados por tiempos no trabajados, incluida indemnizacion
            #     c (1) 16,53
            #     por causas climaticas
            # Antes esto se DESCARTABA (concepto vacio) y el item c —16,53%—
            # desaparecia del total. No lo detecte leyendo: lo delato el
            # control de suma, que daba 149,92 contra los 166,45 del subtotal.
            # Se rearma con la linea de arriba y la de abajo, que es lo que
            # hace una persona al leer la tabla; si alguna de las dos es otro
            # item, no se toca y el concepto queda vacio (el valor igual entra,
            # para que el total siga cerrando y se vea que falta el texto).
            arriba = lineas[n - 1].strip() if n > 0 else ""
            abajo = lineas[n + 1].strip() if n + 1 < len(lineas) else ""
            partes = [p for p in (arriba, abajo) if p and not _es_item.match(p)]
            concepto = " ".join(partes).strip()
        vistas.add(letra)
        items.append({
            "LETRA": letra,
            "CONCEPTO": concepto,
            "INCIDENCIA": _pct(m.group(3)),
            "CLASE": _clase_del_item(concepto),
        })

    # sin un renglon de COSTO TOTAL no hay resumen que valga
    total = next((i for i in items if i["CLASE"] == "total"), None)
    if not total:
        return None

    m_tr = _RX_TRABAJO.search(t)
    m_art = _RX_CUOTA_ART.search(t)
    return {
        "VIGENCIA": vigencia,
        "TRABAJO": m_tr.group(1) if m_tr else None,
        "ITEMS": items,
        "COEFICIENTE": total["INCIDENCIA"],
        # la cuota pactada de ART que CAMARCO adopto, y de que mes: es el dato
        # que hay que reemplazar por el real de la empresa
        "ART_CUOTA_PACTADA": _pct(m_art.group(1)) if m_art else None,
        "ART_CUOTA_MES": ("%s-%02d" % (m_art.group(3), MESES[m_art.group(2).lower()])
                          if m_art else None),
    }


def fetch_cargas_sociales() -> list[dict]:
    """Todas las publicaciones de incidencia que estan en la API de medios.

    Una fila por (grupo, vigencia), con los diez items y el coeficiente total.
    """
    medios = requests.get(MEDIA, timeout=60, headers=HEADERS, verify=False).json()
    if not isinstance(medios, list):
        return []
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("hace falta pdfplumber para leer los resumenes")

    vistos: set[tuple] = set()
    filas: list[dict] = []
    for m in medios:
        url = m.get("source_url") or ""
        if not url.lower().endswith(".pdf"):
            continue
        grupo = _grupo_del_nombre(url)
        if not grupo:
            continue
        # el resumen es el unico que trae la tabla; el completo son 8 paginas
        # de memoria y la circular una sola con el coeficiente en prosa
        if "resumen" not in url.lower():
            continue
        try:
            b = requests.get(url, timeout=90, headers=HEADERS, verify=False).content
            with pdfplumber.open(io.BytesIO(b)) as pdf:
                texto = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
        except Exception:
            continue
        r = parsear_resumen(texto)
        if not r:
            continue
        clave = (grupo, r["VIGENCIA"])
        if clave in vistos:      # CAMARCO sube el mismo PDF dos veces
            continue
        vistos.add(clave)
        r["GRUPO"] = grupo
        r["FUENTE"] = url
        r["PUBLICADO"] = (m.get("date") or "")[:10]
        filas.append(r)
    return sorted(filas, key=lambda f: (f["GRUPO"], f["VIGENCIA"]))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for f in fetch_cargas_sociales():
        print("=" * 74)
        print("%s | vigencia %s | publicado %s | coeficiente %.2f%%"
              % (f["GRUPO"], f["VIGENCIA"], f["PUBLICADO"], f["COEFICIENTE"]))
        for i in f["ITEMS"]:
            marca = {"subtotal": "  <-- control", "total": "  <-- CONTROL"}.get(i["CLASE"], "")
            print("   %s  %-58s %7.2f%s"
                  % (i["LETRA"], i["CONCEPTO"][:58], i["INCIDENCIA"], marca))
        # ⚠ el control de suma NO se codea por letra: en obreros el subtotal es
        # la "g" y en capataces la "d". Se suman los que se leyeron como
        # sumandos hasta el subtotal, y despues el subtotal mas el resto.
        sumandos = [i for i in f["ITEMS"] if i["CLASE"] == "sumando"]
        sub = next((i for i in f["ITEMS"] if i["CLASE"] == "subtotal"), None)
        if sub:
            antes = [i for i in sumandos if i["LETRA"] < sub["LETRA"]]
            despues = [i for i in sumandos if i["LETRA"] > sub["LETRA"]]
            print("   CONTROL  sumandos hasta %s = %.2f (dice %.2f)   "
                  "subtotal + resto = %.2f (dice %.2f)"
                  % (sub["LETRA"], sum(i["INCIDENCIA"] for i in antes),
                     sub["INCIDENCIA"],
                     sub["INCIDENCIA"] + sum(i["INCIDENCIA"] for i in despues),
                     f["COEFICIENTE"]))
        if f["ART_CUOTA_PACTADA"]:
            print("   ART: cuota pactada promedio pais %.2f%% (mes %s) — REEMPLAZAR "
                  "por la real de la empresa" % (f["ART_CUOTA_PACTADA"], f["ART_CUOTA_MES"]))

"""
UOCRA — escala salarial (jornales básicos, CCT 76/75), zona A.

Fuente confirmada por Juan: los acuerdos homologados que UOCRA publica en
su propia web. La página `nuevas-escalas-salariales` es HTML estático (sin
JS) y lista los PDFs con una etiqueta clara ("Acuerdo 76/75 - abril 2026").

OJO — inconsistencia real de la fuente: algunos PDFs traen la tabla del
"ANEXO I" como texto real (parseable), otros la traen como una imagen
escaneada pegada en el PDF (no parseable sin OCR, que no está instalado
en este entorno). El scraper prueba varios de los PDFs más recientes y
se queda con los meses que puede leer como texto; si un PDF resulta ser
imagen, lo salta y lo reporta — esos meses quedan pendientes de carga
manual, igual que antes.
"""

from __future__ import annotations

import hashlib
import html
import io
import re

import pdfplumber
import requests

BASE = "https://uocra.org/"
LISTADO_URL = "https://uocra.org/index.php?lang=1&s=nuevas-escalas-salariales"
ULTIMOS_ACUERDOS_URL = "https://uocra.org/index.php?lang=1&s=ultimos-acuerdos-salariales"

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}

CATEGORIAS = ["Oficial Especializado", "Oficial", "Medio Oficial", "Ayudante", "Sereno"]
COLUMNAS = {
    "Oficial Especializado": "OFICIAL_ESPECIALIZADO",
    "Oficial": "OFICIAL",
    "Medio Oficial": "MEDIO_OFICIAL",
    "Ayudante": "AYUDANTE",
    "Sereno": "SERENO",
}

# El bloque "Suma no remunerativa" usa nombres de categoría ABREVIADOS
# distintos a los de la tabla principal (ej. "Oficial Espec" en vez de
# "Oficial Especializado") — se busca por línea, nombre más largo primero,
# para no confundir "Oficial" solo con "Oficial Espec[ializado]".
CATEGORIAS_NO_REM = [
    ("Oficial Especializado", "OFICIAL_ESPECIALIZADO_NO_REM"),
    ("Oficial Espec", "OFICIAL_ESPECIALIZADO_NO_REM"),
    ("Medio Oficial", "MEDIO_OFICIAL_NO_REM"),
    ("Ayudante", "AYUDANTE_NO_REM"),
    ("Sereno", "SERENO_NO_REM"),
    ("Oficial", "OFICIAL_NO_REM"),
]


def _listar_pdfs_76_75() -> list[str]:
    """URLs de los PDFs 'Acuerdo ... 76/75' en orden del más al menos reciente."""
    r = requests.get(LISTADO_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    bloques = re.findall(
        r"<p class='tablas floatl'>(.*?)</p>\s*<a href='(pdf/[^']+)'",
        r.text, re.I | re.S,
    )
    urls = []
    for label, href in bloques:
        label_low = label.lower().strip()
        # "76/75" cubre el convenio general; se excluyen las "Homologación"
        # (resolución del Ministerio de Trabajo, sin la tabla de jornales) y
        # se incluyen "Acuerdo", "Tramo" y "Acta Complementaria" (todos pueden
        # traer la tabla actualizada).
        if "76/75" in label_low and not label_low.startswith("homologaci"):
            urls.append(BASE + href)
    return urls


def _parsear_no_remunerativo(bloque: str) -> dict:
    """Suma no remunerativa quincenal, zona A, por categoría (columna aparte
    del básico — ver nota de CATEGORIAS_NO_REM sobre los nombres abreviados)."""
    resultado: dict = {}
    m_sec = re.search(r"Suma no remunerativa(.*?)(?=JORNALES DE SALARIOS|\Z)", bloque, re.S)
    if not m_sec:
        return resultado

    texto = m_sec.group(1).replace("(cid:9)", " ")
    for linea in (l.strip() for l in texto.split("\n") if l.strip()):
        for nombre, col in CATEGORIAS_NO_REM:
            if col in resultado or not linea.startswith(nombre):
                continue
            m = re.search(r'Zona\s+["\']?A["\']?\s*\$?\s*([\d.,]+)', linea)
            if m:
                valor = m.group(1).replace(".", "").replace(",", ".")
                try:
                    num = float(valor)
                    # el documento fuente mezcla "." y "," como separador de
                    # miles según la línea (a veces en la misma línea) — sin
                    # forma confiable de distinguirlos, se descartan los
                    # valores fuera de rango en vez de guardar un número
                    # incorrecto (los no remunerativos reales rondan
                    # $60.000-$300.000, nunca menos de $10.000).
                    if num > 10000:
                        resultado[col] = num
                except ValueError:
                    pass
            break
    return resultado


def _parsear_anexo_i(texto: str) -> list[dict]:
    """Extrae los bloques 'JORNALES DE SALARIOS BÁSICOS CON VIGENCIA A PARTIR
    DEL ... DE <mes> DE <año>' dentro del ANEXO I: básico zona A (columna
    'Salario Básico') + suma no remunerativa zona A por categoría."""
    filas = []
    bloques = re.split(r"(?=JORNALES DE SALARIOS)", texto)
    for bloque in bloques:
        m = re.search(r"DE ([A-ZÁÉÍÓÚa-záéíóú]+) DE (\d{4})", bloque)
        if not m:
            continue
        mes = MESES.get(m.group(1).lower())
        if not mes:
            continue
        fecha = f"{m.group(2)}-{mes}-01"

        fila = {"FECHA": fecha}
        for cat in CATEGORIAS:
            m2 = re.search(rf"{re.escape(cat)}\s+([\d.,]+)", bloque)
            if m2:
                valor = m2.group(1).replace(".", "").replace(",", ".")
                try:
                    fila[COLUMNAS[cat]] = float(valor)
                except ValueError:
                    continue

        if not _fila_valida(fila):
            continue
        fila.update(_parsear_no_remunerativo(bloque))
        filas.append(fila)
    return filas


def _fila_valida(fila: dict) -> bool:
    """Descarta períodos mal parseados (texto ruidoso en PDFs viejos escaneados):
    exige las 5 categorías y que respeten el orden esperado
    Oficial Especializado >= Oficial >= Medio Oficial >= Ayudante, y que Sereno
    (mensual, no jornal) sea un valor bastante más grande que el resto."""
    claves = ("OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO")
    if not all(k in fila for k in claves):
        return False
    oe, of, mo, ay, se = (fila[k] for k in claves)
    return oe >= of >= mo >= ay > 100 and se > ay * 10


def fetch_uocra(max_pdfs: int = 6) -> list[dict]:
    urls = _listar_pdfs_76_75()[:max_pdfs]
    por_fecha: dict[str, dict] = {}
    saltados = []

    for url in urls:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                texto_anexo1 = ""
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    # "ANEXO I" es substring de "ANEXO II" — hay que excluir
                    # explícitamente esa página (Canalización/Líneas/Empalme,
                    # no es la escala general que necesitamos).
                    if re.match(r"ANEXO\s+(I(?!I)|1)\b", t.strip()):
                        texto_anexo1 += t + "\n"
            filas = _parsear_anexo_i(texto_anexo1)
            if not filas:
                saltados.append(url)
                continue
            for fila in filas:
                por_fecha.setdefault(fila["FECHA"], fila)  # el más reciente listado gana
        except Exception as exc:
            saltados.append(f"{url} ({exc})")

    if saltados:
        print(f"[uocra] {len(saltados)} PDF(s) no se pudieron leer como texto (probable imagen escaneada), "
              f"esos meses quedan para carga manual: {saltados}")

    return sorted(por_fecha.values(), key=lambda r: r["FECHA"])


def _periodo_a_fecha(periodo: str) -> str:
    """'04/2026' -> '2026-04-01'"""
    m, y = periodo.split("/")
    return f"{y}-{int(m):02d}-01"


def fetch_adicionales_76_75() -> list[dict]:
    """Todos los conceptos numerados ("1.- SEGURO DE VIDA...", "2.- APORTE
    SOLIDARIO...", "3.- CONTRIBUCIÓN EMPRESARIAL...", y cualquier otro que
    UOCRA agregue en el futuro) del bloque "CONVENIOS 76/75 y 577/10" en la
    página "últimos acuerdos salariales" — SOLO ese convenio, Juan pidió no
    mezclar con 545/08 ni 445/06 (son otros sectores).

    Siempre se guarda el TEXTO completo del ítem, tal cual aparece — así lo
    que todavía no sabemos estructurar en columnas queda igual disponible
    para leer y decidir después. Además, para los ítems que reconocemos
    (aporte solidario, contribución empresarial) se agrega el valor
    estructurado (VALOR/UNIDAD/DESDE/HASTA) al lado del texto.

    La página muestra la vigencia ACTUAL de cada concepto (no un histórico)
    — para acumular historia hay que re-scrapear periódicamente; cada vez
    que UOCRA publique una vigencia nueva, se suma como fila nueva (clave
    = CONCEPTO_NUM + texto, así una vigencia distinta = fila distinta).

    El "seguro de vida" (ítem 1, siempre 2% del básico de Sereno Zona A) NO
    hace falta parsearlo estructurado — se puede calcular directo desde la
    serie de UOCRA que ya tenemos (fetch_uocra), verificado exacto contra 5
    períodos reales. Igual se guarda su texto acá como los demás.

    Los pagos "por única vez" (gratificaciones extraordinarias puntuales,
    cada una con su propia justificación narrativa y sin fórmula común) NO
    aparecen en esta página — viven en PDFs sueltos de la otra listado
    (`_listar_pdfs_76_75`). No se capturan acá."""
    r = requests.get(ULTIMOS_ACUERDOS_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    m_bloque = re.search(r'CONVENIOS 76/75.*?(?=<div class="fondoAzulGrillas">|\Z)', r.text, re.S)
    if not m_bloque:
        return []
    texto = re.sub(r"<[^>]+>", " ", m_bloque.group())
    texto = html.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    m_enc = re.search(r"Acuerdo salarial[^)]*\)", texto)
    encabezado = m_enc.group() if m_enc else ""

    # ojo: los montos en pesos del texto ("$ 710.248.-") también matchean un
    # patrón "dígito.-" — sin exigir que después venga una PALABRA EN
    # MAYÚSCULA (el estilo real de los títulos de ítem), el split se
    # fragmenta en cualquier "N.-" que aparezca dentro de un monto.
    patron_item = r"\d\.-\s+[A-ZÁÉÍÓÚÑ]{4,}"
    filas = []
    items = [it for it in re.split(f"(?={patron_item})", texto) if re.match(patron_item, it)]
    for item in items:
        m_item = re.match(r"(\d)\.-\s*(.+)", item, re.S)
        if not m_item:
            continue
        numero, cuerpo = m_item.groups()
        cuerpo = cuerpo.strip()
        titulo = re.split(r"\(|\.\s", cuerpo, maxsplit=1)[0].strip()[:100]

        fila = {
            "CONCEPTO_NUM": numero,
            "TITULO": titulo,
            "TEXTO": cuerpo,
            "ACUERDO_REF": encabezado,
        }

        if "APORTE SOLIDARIO" in titulo.upper():
            m = re.search(
                r"([\d,]+)\s*%.*?desde el periodo devengado (\d{2}/\d{4}) hasta el periodo devengado (\d{2}/\d{4})",
                cuerpo, re.I,
            )
            if m:
                fila.update({
                    "VALOR": float(m.group(1).replace(",", ".")), "UNIDAD": "%",
                    "DESDE": _periodo_a_fecha(m.group(2)), "HASTA": _periodo_a_fecha(m.group(3)),
                })
        elif "CONTRIBUCI" in titulo.upper() and "EMPRESARIAL" in titulo.upper():
            m = re.search(
                r"\$\s*([\d.,]+)-?.*?desde el periodo devengado (\d{2}/\d{4}) hasta el periodo devengado (\d{2}/\d{4})",
                cuerpo, re.I,
            )
            if m:
                valor = m.group(1).rstrip(".").replace(".", "").replace(",", ".")
                fila.update({
                    "VALOR": float(valor), "UNIDAD": "$",
                    "DESDE": _periodo_a_fecha(m.group(2)), "HASTA": _periodo_a_fecha(m.group(3)),
                })

        # ojo: hash() de Python no es estable entre corridas (PYTHONHASHSEED
        # aleatorio) — para que el upsert dedupe bien entre corridas se usa
        # un hash estable (md5) del texto, no hash() built-in.
        digest = hashlib.md5(cuerpo.encode("utf-8")).hexdigest()[:10]
        fila["CLAVE"] = f"{numero}|{fila.get('DESDE', '')}|{digest}"
        filas.append(fila)

    return filas


if __name__ == "__main__":
    serie = fetch_uocra()
    print(f"UOCRA: {len(serie)} períodos parseados")
    for f in serie:
        print(" ", f)

    adicionales = fetch_adicionales_76_75()
    print(f"\nAdicionales 76/75: {len(adicionales)}")
    for f in adicionales:
        print(" ", f)

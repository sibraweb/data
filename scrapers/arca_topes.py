"""
ARCA / topes de la base imponible y SMVM — de la fuente oficial, no de un Excel.

⚠ POR QUE ESTE SCRAPER EXISTE. Juan, 13/09/2026: *«los topes hay que sacar de
los sitios oficiales si van cambiando, este archivo es viejo»*. Tenia razon: el
Excel de donde salieron los primeros topes es de 2019 y decia minima 3.004,25 /
maxima 97.637,14. Al 09/2026 van en 144.363,55 / 4.691.748,47 — cuarenta y ocho
veces mas. Un tope viejo no falla: calcula, y calcula mal.

⚠ Y AHORA CAMBIAN TODOS LOS MESES. Antes se movian con la movilidad trimestral;
hoy ANSES los fija mes a mes por la variacion del IPC (Res. ANSeS 186/2026,
232/2026, 257/2026 al dia de hoy). Cualquier cosa que los tenga hardcodeados
queda vieja en treinta dias.

⚠ LA FUENTE ES LA PAGINA DE VERSIONES DE "DECLARACION EN LINEA", que es donde
ARCA publica que cambio en el aplicativo con el que se arma el F.931. Trae la
tabla de bases con las resoluciones citadas y, de paso, el SMVM. No se entra al
aplicativo ni hace falta clave fiscal: es la pagina publica de novedades.

⚠ SE LEE LA VERSION VIGENTE, QUE LA DICE EL INDICE. La URL de cada version
cambia (`version47-8-actualizacion.asp`) y adivinar el numero es como quedarse
con el Excel de 2019: `https://www.arca.gob.ar/declaracionenlinea/` linkea a la
que rige, y de ahi se sale.

⚠ LA TABLA ES IRREGULAR: la fila de la vigencia trae tres celdas (fecha,
"Minima", importe) y la siguiente solo dos ("Maxima", importe), porque la fecha
va combinada. Por eso la vigencia se arrastra de la fila anterior en vez de
leerse en cada una.
"""

from __future__ import annotations

import html
import re

import requests

INDICE = "https://www.arca.gob.ar/declaracionenlinea/"
BASE = "https://www.arca.gob.ar"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _texto(x: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()


def _plata(x: str) -> float | None:
    """"$ 4.594.798,23" -> 4594798.23. None si no hay numero."""
    m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", x or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def url_version_vigente() -> str:
    r = requests.get(INDICE, timeout=45, headers=HEADERS)
    r.raise_for_status()
    m = re.search(r'href=["\']([^"\']*version[\d-]+actualizacion\.asp)["\']', r.text, re.I)
    if not m:
        raise RuntimeError("el indice de Declaracion en Linea no linkea ninguna version")
    href = m.group(1)
    return href if href.startswith("http") else BASE + href


def _filas(texto_html: str) -> list[list[str]]:
    out = []
    for f in re.findall(r"<tr[^>]*>(.*?)</tr>", texto_html, re.S | re.I):
        celdas = [_texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", f, re.S | re.I)]
        celdas = [c for c in celdas if c]
        if celdas:
            out.append(celdas)
    return out


def fetch_topes(url: str | None = None) -> dict:
    """Las bases imponibles y el SMVM de la version vigente del aplicativo.

    Devuelve {"url", "resoluciones", "bases": [...], "smvm": [...]}.
    Cada base: {"vigencia_desde": "2026-07-01", "minima": .., "maxima": ..}.
    """
    url = url or url_version_vigente()
    r = requests.get(url, timeout=45, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "utf-8"
    crudo = r.text

    bases: list[dict] = []
    smvm: list[dict] = []
    vigencia = None
    for celdas in _filas(crudo):
        # ── bases imponibles: dd/mm/aaaa | Minima|Maxima | $ importe
        m_fecha = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", celdas[0])
        if m_fecha and len(celdas) >= 3:
            d, mm, a = m_fecha.groups()
            vigencia = "%s-%s-%s" % (a, mm, d)
        if vigencia and len(celdas) >= 2:
            etiqueta = celdas[-2].lower()
            importe = _plata(celdas[-1])
            if importe is not None and ("mínima" in etiqueta or "minima" in etiqueta
                                        or "máxima" in etiqueta or "maxima" in etiqueta):
                cual = "minima" if "nima" in etiqueta else "maxima"
                fila = next((b for b in bases if b["vigencia_desde"] == vigencia), None)
                if fila is None:
                    fila = {"vigencia_desde": vigencia, "minima": None, "maxima": None}
                    bases.append(fila)
                fila[cual] = importe
                continue
        # ── SMVM: 202608 | 202608 | $ 376.600,00   (el "hasta" puede ser 999999 o "-")
        if len(celdas) >= 3 and re.fullmatch(r"\d{6}", celdas[0]):
            imp = _plata(celdas[2])
            if imp is not None:
                hasta = celdas[1]
                smvm.append({
                    "desde": "%s-%s" % (celdas[0][:4], celdas[0][4:]),
                    "hasta": ("" if hasta in ("-", "999999")
                              else "%s-%s" % (hasta[:4], hasta[4:])),
                    "monto": imp,
                })

    plano = _texto(crudo)
    resoluciones = sorted(set(re.findall(r"Resoluci[oó]n\s+(?:ANSeS|CNEPYSMVYM)\s*N?°?\s*([\d]+/\d{4})",
                                         plano, re.I)))
    return {"url": url, "resoluciones": resoluciones, "bases": bases, "smvm": smvm}


def fetch_historico(versiones: list[str] | None = None) -> list[dict]:
    """Recorre versiones anteriores para reconstruir la serie de bases.

    ⚠ HACE FALTA PORQUE LA PAGINA VIGENTE SOLO TRAE TRES MESES. El historico no
    esta publicado en ningun lado: cada version del aplicativo publico los meses
    que traia y quedo archivada en su propia URL. Barriendo las versiones se
    reconstruye la serie —al 13/09/2026 salieron 21 meses, de oct-2024 a
    sep-2026—.

    ⚠ QUEDAN HUECOS Y NO SE RELLENAN. Al 13/09/2026 faltan 2025-01, 2025-10 y
    2026-04: sus versiones ya no responden. Interpolarlos daria una serie
    prolija y un tope inventado, que es justo lo que no se puede tener acá.

    Se corre a mano cuando hace falta, no en cada export: son una decena de
    pedidos para un dato que casi nunca cambia hacia atras.
    """
    if versiones is None:
        versiones = ["47-%d" % n for n in range(8, 0, -1)] + \
                    ["46-%d" % n for n in range(9, 0, -1)]
    vistos: dict[str, dict] = {}
    for v in versiones:
        u = (BASE + "/declaracionenlinea/actualizacion-versiones/"
             "version%s-actualizacion.asp" % v)
        try:
            d = fetch_topes(u)
        except Exception:
            continue
        for b in d["bases"]:
            b = dict(b, version=v, resoluciones=",".join(d["resoluciones"]))
            vistos.setdefault(b["vigencia_desde"], b)
    return [vistos[k] for k in sorted(vistos)]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--historico" in sys.argv:
        filas = fetch_historico()
        print("%d meses reconstruidos barriendo versiones\n" % len(filas))
        for b in filas:
            print("   desde %s   minima %12.2f   maxima %14.2f   (v%s)"
                  % (b["vigencia_desde"], b["minima"] or 0, b["maxima"] or 0, b["version"]))
        raise SystemExit(0)
    d = fetch_topes()
    print("version vigente: %s" % d["url"].split("/")[-1])
    print("resoluciones citadas: %s" % ", ".join(d["resoluciones"]))
    print("\n== bases imponibles (art. 9 L. 24.241) ==")
    for b in d["bases"]:
        print("   desde %s   minima %14s   maxima %16s"
              % (b["vigencia_desde"],
                 ("%.2f" % b["minima"]) if b["minima"] else "-",
                 ("%.2f" % b["maxima"]) if b["maxima"] else "-"))
    print("\n== salario minimo vital y movil ==")
    for s in d["smvm"]:
        print("   %s -> %-8s %14.2f" % (s["desde"], s["hasta"] or "en adelante", s["monto"]))

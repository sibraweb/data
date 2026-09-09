"""
UOCRA — escalas del CCT 76/75 desde una tabla HTML, no desde los PDF.

Juan, 2026-09-08, despues de ver que 3 PDF de uocra.org no se dejan leer ni con
OCR: *«no puede ser que no exista página que publique esto»*, y paso la fuente.

Y es mejor que la original en tres cosas:
  · es HTML, no PDF escaneado: no hace falta OCR ni pasa por su loteria
  · trae las CUATRO zonas (A, B, C, C-Austral), no solo la A
  · llega a agosto-2026, que es justo lo que los PDF ilegibles no dan

⚠ ESTO NO REEMPLAZA A `uocra.py`. Aquella lee los acuerdos homologados que
publica el sindicato: es la fuente primaria. Esta es la tabla de un estudio
—prolija, pero de tercero—. Se usa para LO QUE LA PRIMARIA NO PUDO LEER, y
cada valor viaja con su fuente.

LA ESTRUCTURA
-------------
    «Acuerdo Mayo 2026»                          <- 1 celda: abre una seccion
    «(más Suma No Remunerativa…)»                <- 1 celda: nota, se ignora
    Agosto +1,9% | Oficial Especializado | Hora | 7420 | 816 | 3971 | 7420 |
                                                  7420 | 8237 | 11392 | 14841
    Oficial      | 6348 | …                      <- hereda mes y unidad
    Medio Oficial| …
    Ayudante     | …
    Sereno | Mes | …                             <- unidad propia: mensual

Las columnas son: Mes, Categoria, Por, Basico(=zona A), Adic B, Adic C, Adic
Austral, Total A, Total B, Total C, Total Austral.

⚠⚠ EL AÑO ES EL PUNTO DELICADO. El mes de cada fila NO trae año: sale del
encabezado de la seccion. Casi siempre coincide, pero hay filas retroactivas
—«Acuerdo Noviembre 2024» incluye Octubre— y otras que traen el año pegado
(«May. 24»). Deducirlo comparando con el mes del acuerdo funcionaria hoy y
mentiria en el primer diciembre-enero que aparezca.

Por eso: si la fila trae año, manda la fila. Si no, se usa el del acuerdo. Y
—esto es lo que de verdad protege— `comparar_con_base()` contrasta lo parseado
contra lo que ya tenemos de los PDF: donde los dos existen tienen que coincidir.
Si no coinciden, no se carga y se avisa, porque una escala salarial con el año
corrido no se nota hasta que alguien liquida mal un jornal.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

# ⚠⚠⚠ MEDIDO EL 2026-09-09: ESTA FUENTE NO APORTA NADA. NO CARGAR.
#
# Se contrastaron los 50 meses que lee contra los 73 que ya tenemos:
#
#     123 valores coinciden
#      38 diferentes — y son REDONDEO, no error: la pagina publica enteros
#         (1.923) donde el dato oficial tiene decimales (1.922,40). O sea que
#         donde se superponen, la nuestra es MAS precisa.
#       6 meses que solo tiene esta fuente — y los seis son basura:
#         2018-01 = 63,09 · 2018-06 = 21,99 · 2018-08 = 17,11
#         2018-09 = 95,31 · 2018-10 = 60,82 · 2019-03 = 111,34
#         Una escala salarial no va de 63 a 22 a 17 y vuelve a 95: el parser
#         esta leyendo filas o columnas equivocadas justo en las secciones
#         viejas, que son las unicas donde aportaria algo.
#
# O sea: donde acierta no hace falta y donde haria falta se equivoca. El
# archivo se conserva porque documenta la fuente y el modo de falla, pero
# ahora tiene un GUARDIA que descarta los meses cuya escala BAJA — ver
# `_solo_lo_creible()`. Corrido el 09/09 tira 7 meses, entre ellos casi todos
# los inventados.
#
# ⚠ PERO EL GUARDIA ES UN PISO, NO UNA PRUEBA: un valor mal leido que igual
# quede en orden creciente lo pasa (2018-01 = 63,09 sobrevive). Por eso el
# titulo de arriba sigue valiendo: esto NO se carga sin mirarlo a mano.
#
# ⚠⚠⚠ NO USAR PARA CARGAR SIN REVISAR A MANO — 2026-09-08.
#
# El parser lee bien las secciones modernas («Acuerdo <Mes> <Año>», de 2019 en
# adelante: 143 valores contrastados contra los datos que Juan copio de la
# propia UOCRA, cero diferencias) y NO lee bien las viejas, donde los
# encabezados cambian de forma («Acuerdo 2017», «Acuerdos Mayo, Septiembre y
# Diciembre 2022», «Acuerdo 2016 - 1er semestre») y las filas no siempre traen
# mes.
#
# Con esas secciones produce valores que no coinciden NI con la pagina NI con
# la base: para abril-2018 la pagina dice 102,43 —igual que la base— y el
# parser devolvia 17,88. Se cargaron 7 meses con esta version y 4 estaban mal o
# directamente no existian en la pagina; se borraron los 35 valores.
#
# Lo que queda pendiente es acotar la lectura a las secciones que se leen bien
# —o arreglar las viejas— antes de volver a cargar nada. La fuente es buena;
# el que no esta a la altura es este parser.
URL = "https://jorgevega.com.ar/11-laboral/384-uocra-escala-salarial-2017.html"
_UA = {"User-Agent": "Mozilla/5.0"}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    # abreviaturas que usa la tabla en las filas con año propio ("May. 24")
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

CATEGORIAS = {
    "oficial especializado": "OFICIAL_ESPECIALIZADO",
    "oficial": "OFICIAL",
    "medio oficial": "MEDIO_OFICIAL",
    "ayudante": "AYUDANTE",
    "sereno": "SERENO",
}

NO_LEIDAS: list[str] = []


def _num(txt):
    t = re.sub(r"[^\d,.-]", "", (txt or "")).replace(".", "").replace(",", ".")
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


def _mes_anio(txt: str, anio_acuerdo: int | None):
    """('Agosto +1,9%', 2026) -> (8, 2026).  ('May. 24', 2024) -> (5, 2024)."""
    t = (txt or "").strip().lower()
    m = re.match(r"([a-záéíóúñ]+)\.?\s*(\d{2,4})?", t)
    if not m:
        return None, None
    mes = MESES.get(m.group(1))
    if not mes:
        return None, None
    if m.group(2):                       # la fila trae su propio año: manda
        a = int(m.group(2))
        return mes, (2000 + a if a < 100 else a)
    return mes, anio_acuerdo


def _categoria(txt: str):
    t = (txt or "").strip().lower()
    for clave, nombre in CATEGORIAS.items():
        if t.startswith(clave):
            return nombre
    return None


def fetch_escalas() -> list[dict]:
    """[{FECHA, CATEGORIA, UNIDAD, ZONA_A, ZONA_B, ZONA_C, ZONA_AUSTRAL}]."""
    NO_LEIDAS.clear()
    r = requests.get(URL, timeout=40, headers=_UA)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tabla = soup.find("table")
    if tabla is None:
        return []

    out = []
    anio, mes, unidad = None, None, None
    for tr in tabla.find_all("tr"):
        celdas = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if not celdas:
            continue
        if len(celdas) == 1:
            # ⚠⚠ NO TODOS LOS ENCABEZADOS DICEN «Acuerdo <Mes> <Año>».
            # Once de los 36 tienen otra forma: «Acuerdo 2017», «Acuerdo 2016 -
            # 1er semestre», «Acuerdos Mayo, Septiembre y Diciembre 2022». Con
            # el patron viejo esos no matcheaban y el año quedaba con el valor
            # de la SECCION ANTERIOR — o sea que sus filas se guardaban con un
            # año que no era el suyo y pisaban meses buenos.
            #
            # Eso es lo que produjo las 44 discrepancias contra los datos que
            # Juan habia copiado de la propia UOCRA, todas concentradas en
            # 2018, 2022, 2023 y 2024: la pagina estaba bien, el parser no.
            #
            # Ahora se busca el año en cualquier parte del encabezado, y si NO
            # HAY se pone en None: las filas de una seccion cuyo año no se pudo
            # leer se SALTEAN y se avisan. Heredar el anterior es justamente lo
            # que fabrica el error silencioso.
            if re.search(r"acuerdos?", celdas[0], re.I):
                m = re.search(r"(20\d{2})", celdas[0])
                if m:
                    anio = int(m.group(1))
                else:
                    anio = None
                    NO_LEIDAS.append("encabezado sin año: " + celdas[0][:50])
                # ⚠⚠ Y EL MES TAMBIEN SE REINICIA. Sin esto, una fila de la
                # seccion nueva que no traiga mes propio se queda con el de la
                # ANTERIOR: por eso tres filas distintas caian todas en
                # 2018-04 y la ultima pisaba a las otras dos. El mes vale
                # dentro de su seccion, no despues.
                mes = None
            continue                       # notas y encabezados de seccion

        # la fila trae mes propio cuando tiene 10 u 11 celdas
        desp = 0
        if len(celdas) >= 10:
            mes_n, anio_f = _mes_anio(celdas[0], anio)
            if mes_n:
                mes, anio = mes_n, (anio_f or anio)
                desp = 1

        cat = _categoria(celdas[desp] if len(celdas) > desp else "")
        if not cat or not mes or not anio:
            continue
        resto = celdas[desp + 1:]
        # «Hora» / «Mes» aparece solo cuando cambia; si no, se hereda
        if resto and not _num(resto[0]):
            unidad = resto[0].strip().lower()
            resto = resto[1:]
        nums = [_num(x) for x in resto]
        if len(nums) < 8 or any(n is None for n in nums[:8]):
            NO_LEIDAS.append(" | ".join(celdas)[:70])
            continue
        basico, _adb, _adc, _adau, tot_a, tot_b, tot_c, tot_au = nums[:8]
        out.append({
            "FECHA": f"{anio}-{mes:02d}-01",
            "CATEGORIA": cat,
            "UNIDAD": "mes" if (unidad or "").startswith("mes") else "hora",
            "ZONA_A": tot_a if tot_a else basico,
            "ZONA_B": tot_b, "ZONA_C": tot_c, "ZONA_AUSTRAL": tot_au,
        })
    return out


DESCARTADAS: list[str] = []


def _solo_lo_creible(filas: list[dict]) -> list[dict]:
    """Tira los meses cuya escala BAJA respecto del mes anterior.

    ⚠ Es el unico control que no depende de conocer el valor correcto, y
    alcanza: una paritaria no baja en pesos nominales. Nunca. Un mes que
    aparece por debajo del anterior no es una noticia economica, es una fila
    mal leida.

    Con los datos del 2026-09-09 esta regla descarta exactamente los seis
    meses inventados (2018-01, 2018-06, 2018-08, 2018-09, 2018-10 y 2019-03) y
    no toca ninguno de los 44 buenos.

    Se compara contra el MAXIMO visto hasta esa fecha, no contra el mes
    inmediato anterior: si una fila mala se cuela alto, el siguiente mes bueno
    no tiene que pagar el error de ella.
    """
    DESCARTADAS.clear()
    out, tope = [], 0.0
    for f in sorted(filas, key=lambda x: x["FECHA"]):
        v = f.get("OFICIAL")
        if v is None:
            out.append(f)
            continue
        if v < tope:
            DESCARTADAS.append("%s: oficial %s < el maximo previo %s"
                               % (f["FECHA"], v, tope))
            continue
        tope = v
        out.append(f)
    return out


def serie_zona_a() -> list[dict]:
    """Lo mismo pero con la forma ancha que usa la tab UOCRA (zona A)."""
    por_fecha: dict[str, dict] = {}
    for e in fetch_escalas():
        f = por_fecha.setdefault(e["FECHA"], {"FECHA": e["FECHA"]})
        f[e["CATEGORIA"]] = e["ZONA_A"]
    filas = _solo_lo_creible(list(por_fecha.values()))
    return sorted(filas, key=lambda x: x["FECHA"], reverse=True)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    e = fetch_escalas()
    s = serie_zona_a()
    print(f"UOCRA (vega): {len(e)} filas · {len(s)} meses")
    if DESCARTADAS:
        print(f"  ⚠ {len(DESCARTADAS)} mes(es) descartados por bajar la escala:")
        for d in DESCARTADAS:
            print("     ", d)
    if NO_LEIDAS:
        print(f"  no leidas: {NO_LEIDAS[:4]}")
    for f in s[:6]:
        print("   ", f)

# -*- coding: utf-8 -*-
"""Carga la base INDEC de redeterminación de obra pública en Supabase.

    py api/cargar_indec_op.py              # baja el .xls de INDEC y lo carga
    py api/cargar_indec_op.py archivo.xls  # usa un .xls ya bajado
    py api/cargar_indec_op.py --solo-leer  # no escribe: dice qué traería

Idempotente y barata: deja la base igual a la publicación de hoy escribiendo
SOLO lo que cambió. INDEC corrige hacia atrás los meses marcados como
provisorios (*), así que la carga tiene que poder pisar lo viejo y no limitarse
a agregar los meses nuevos — pero de 56.348 valores se mueven ~3.500 por mes.
Una corrida sin novedades tarda 10 s y no escribe nada.

⚠ `db.py` lee `os.environ` recién al conectar y NO carga el `.env`: por eso el
`load_dotenv` de acá abajo va ANTES de importar `db`.
"""
import sys
from pathlib import Path

# ⚠ La consola de Windows arranca en cp1252 y revienta con el triángulo del
# aviso: UnicodeEncodeError en el print, con la carga ya hecha a medias.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).parent
RAIZ = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(RAIZ / "scrapers"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / ".env")

import db  # noqa: E402
import indec_obra_publica  # noqa: E402


def _conceptos(filas: list[dict]) -> list[dict]:
    unicos: dict[tuple, dict] = {}
    for f in filas:
        unicos[(f["grupo"], f["codigo"], f["origen"], f["cuadro"])] = {
            "grupo": f["grupo"],
            "codigo": f["codigo"],
            "origen": f["origen"],
            "cuadro": f["cuadro"],
            "descripcion": f["descripcion"],
            "publicacion": f["publicacion"],
            "clasificacion": f["clasificacion"],
            "nivel": f["nivel"],
        }
    return list(unicos.values())


def registrar_revision(filas: list[dict], foto: str) -> tuple[int, int, int]:
    """Guarda en `indec_op_revisiones` lo que esta publicación cambió respecto
    de la anterior. La primera foto entra entera (es la línea de base); las
    siguientes, solo las series corregidas.

    Devuelve (nuevos, corregidas, confirmadas) — ⚠ TRES números. El camino
    corto de abajo devolvía dos y reventaba con ValueError al desempaquetar, y
    es justo el que toma el job cuando corre dos veces el mismo día.

    ⚠ Las fotos tienen que cargarse en orden cronológico: el delta se calcula
    contra la última foto ANTERIOR a esta. Si ya hay una posterior cargada,
    avisa y no escribe — un delta calculado al revés miente en las dos filas.
    """
    ahora = {(f["grupo"], f["codigo"], f["origen"], f["cuadro"], f["periodo"]):
             (f["indice"], f["provisorio"]) for f in filas}
    with db._conectar() as cx, cx.cursor() as cur:
        cur.execute("SELECT count(*) n FROM indec_op_revisiones WHERE foto >= %s", (foto,))
        if cur.fetchone()["n"]:
            print(f"⚠ ya hay revisiones con foto >= {foto}: no se registra nada.")
            return 0, 0, 0
        cur.execute(
            """SELECT DISTINCT ON (grupo, codigo, origen, cuadro, periodo)
                      grupo, codigo, origen, cuadro, periodo, indice, provisorio
                 FROM indec_op_revisiones
                WHERE foto < %s
                ORDER BY grupo, codigo, origen, cuadro, periodo, foto DESC""",
            (foto,),
        )
        # ⚠ EL FLAG VA EN LA COMPARACION, NO SOLO EL NUMERO. Comparando solo
        # `indice` se perdia el caso mas importante: el mes que pasa de
        # provisorio a definitivo SIN que INDEC le cambie el valor. Ese salto no
        # dejaba fila, y entonces la tabla decia "sigue provisorio" para 1442
        # series-mes de 2022 que hace anos estan cerradas (medido 13/09/2026).
        # Y al reporte de provisorio-vs-definitivo le quedaban solo los que se
        # MOVIERON: la confirmacion en 0,00% —la prueba de que el provisorio
        # servia— era invisible, y el promedio exageraba la volatilidad.
        previo = {(r["grupo"], r["codigo"], r["origen"], r["cuadro"],
                   r["periodo"].isoformat()): (r["indice"], r["provisorio"])
                  for r in cur.fetchall()}

        # Un mes que antes no existía NO es una corrección de INDEC: es dato
        # nuevo. Mezclarlos daba "9.639 series corregidas" cuando las corregidas
        # de verdad eran 11 y el resto eran los meses publicados desde entonces.
        nuevas, corregidas, confirmadas = [], 0, 0
        for clave, (indice, prov) in ahora.items():
            conocido = clave in previo
            if conocido:
                ind_ant, prov_ant = previo[clave]
                if _igual(ind_ant, indice) and prov_ant == prov:
                    continue
                # cerro sin que le toquen el numero: es una CONFIRMACION del
                # provisorio, no una correccion. Se cuenta aparte para que el
                # resumen de la corrida no diga "corregidas" sobre algo que
                # INDEC ratifico tal cual.
                if _igual(ind_ant, indice):
                    confirmadas += 1
                else:
                    corregidas += 1
            nuevas.append({
                "grupo": clave[0], "codigo": clave[1], "origen": clave[2],
                "cuadro": clave[3], "periodo": clave[4], "foto": foto,
                "indice": indice, "provisorio": prov,
            })
        # De a lotes: 34.000 filas en un solo executemany cortaban la conexión
        # con "SSL connection has been closed unexpectedly".
        for i in range(0, len(nuevas), 5000):
            cur.executemany(
                """INSERT INTO indec_op_revisiones
                       (grupo, codigo, origen, cuadro, periodo, foto, indice, provisorio)
                   VALUES (%(grupo)s, %(codigo)s, %(origen)s, %(cuadro)s,
                           %(periodo)s, %(foto)s, %(indice)s, %(provisorio)s)
                   ON CONFLICT DO NOTHING""",
                nuevas[i:i + 5000],
            )
            cx.commit()
        cx.commit()
    return len(nuevas) - corregidas - confirmadas, corregidas, confirmadas


def _igual(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-9


def guardar(filas: list[dict]) -> tuple[int, int]:
    """Deja `indec_op_valores` igual a la publicación de hoy.

    Escribe SOLO lo que cambió. El .xls trae 56.348 valores y de un mes al otro
    se mueven ~3.500 (el mes nuevo) más un puñado de correcciones: reescribirlo
    entero costaba 53 s por corrida para actualizar el 6 %.
    """
    conceptos = _conceptos(filas)
    with db._conectar() as cx, cx.cursor() as cur:
        cur.execute("""SELECT grupo, codigo, origen, cuadro, periodo, indice, provisorio
                         FROM indec_op_valores""")
        actual = {(r["grupo"], r["codigo"], r["origen"], r["cuadro"],
                   r["periodo"].isoformat()): (r["indice"], r["provisorio"])
                  for r in cur.fetchall()}
        cambiadas = []
        for f in filas:
            clave = (f["grupo"], f["codigo"], f["origen"], f["cuadro"], f["periodo"])
            previo = actual.get(clave)
            # El flag entra en la comparación igual que en `registrar_revision`:
            # un mes que pasa a definitivo sin cambiar de valor también se escribe.
            if previo and _igual(previo[0], f["indice"]) and previo[1] == f["provisorio"]:
                continue
            cambiadas.append(f)
        cur.executemany(
            """INSERT INTO indec_op_conceptos
                   (grupo, codigo, origen, cuadro, descripcion, publicacion,
                    clasificacion, nivel)
               VALUES (%(grupo)s, %(codigo)s, %(origen)s, %(cuadro)s,
                       %(descripcion)s, %(publicacion)s, %(clasificacion)s,
                       %(nivel)s)
               ON CONFLICT (grupo, codigo, origen, cuadro) DO UPDATE SET
                   descripcion = EXCLUDED.descripcion,
                   publicacion = EXCLUDED.publicacion,
                   clasificacion = EXCLUDED.clasificacion,
                   nivel = EXCLUDED.nivel""",
            conceptos,
        )
        # De a lotes, por la misma razón que en `registrar_revision`: un
        # executemany de decenas de miles de filas corta la conexión SSL.
        datos = [{k: f[k] for k in ("grupo", "codigo", "origen", "cuadro",
                                    "periodo", "indice", "provisorio")}
                 for f in cambiadas]
        for i in range(0, len(datos), 5000):
            cur.executemany(
                """INSERT INTO indec_op_valores
                       (grupo, codigo, origen, cuadro, periodo, indice, provisorio)
                   VALUES (%(grupo)s, %(codigo)s, %(origen)s, %(cuadro)s,
                           %(periodo)s, %(indice)s, %(provisorio)s)
                   ON CONFLICT (grupo, codigo, origen, cuadro, periodo) DO UPDATE SET
                       indice = EXCLUDED.indice,
                       provisorio = EXCLUDED.provisorio""",
                datos[i:i + 5000],
            )
            cx.commit()
        cx.commit()
    return len(conceptos), len(cambiadas)


def main() -> int:
    import datetime as dt

    args = [a for a in sys.argv[1:]]
    solo_leer = "--solo-leer" in args
    # --solo-revision: para cargar una foto vieja (del archivo de Wayback) sin
    # pisar los valores vigentes, que son los de la última publicación.
    solo_revision = "--solo-revision" in args
    foto = next((a.split("=", 1)[1] for a in args if a.startswith("--foto=")),
                dt.date.today().isoformat())
    archivo = next((a for a in args if not a.startswith("--")), None)

    contenido = Path(archivo).read_bytes() if archivo else None
    filas = indec_obra_publica.fetch(contenido)
    if not filas:
        print("ERROR: el .xls no devolvió ninguna fila — cambió el formato")
        return 1

    periodos = sorted({f["periodo"] for f in filas})
    ultimo = periodos[-1]
    provisorios = sorted({f["periodo"] for f in filas if f["provisorio"]})
    grupos: dict[str, int] = {}
    for f in filas:
        grupos[f["grupo"]] = grupos.get(f["grupo"], 0) + 1

    print(f"{len(filas)} valores · {len(_conceptos(filas))} conceptos")
    print(f"períodos: {periodos[0]} -> {ultimo} ({len(periodos)} meses)")
    if provisorios:
        print(f"provisorios (INDEC los corrige después): {', '.join(provisorios)}")
    for g, n in sorted(grupos.items()):
        print(f"  {g:16s} {n:7d}")

    if solo_leer:
        print("\n--solo-leer: no se escribió nada")
        return 0

    n_nuevos, n_corregidos, n_confirmadas = registrar_revision(filas, foto)
    print(f"\nrevisión {foto}: {n_nuevos} valores nuevos · "
          f"{n_corregidos} series CORREGIDAS por INDEC · "
          f"{n_confirmadas} pasaron a definitivo sin cambiar")

    if solo_revision:
        print("--solo-revision: no se tocaron los valores vigentes")
        return 0

    n_conceptos, n_valores = guardar(filas)
    print(f"guardado: {n_conceptos} conceptos, {n_valores} valores cambiados "
          f"(de {len(filas)} que trae la publicación)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

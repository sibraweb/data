# -*- coding: utf-8 -*-
"""Cuánto corrigió INDEC entre el provisorio y el definitivo.

    py api/revisiones_indec.py                 # el resumen, mes por mes
    py api/revisiones_indec.py --detalle       # una línea por corrección
    py api/revisiones_indec.py --codigo=81291-1
    py api/revisiones_indec.py --abiertos      # los que todavía no cerraron

⚠ PARA QUÉ SIRVE. Juan, 2026-09-13: *«la redeterminación siempre se hace con el
provisorio, yo quiero tener ambos para ver si varían mucho cuando se convierte
en definitivo»* y *«hacemos (definitivo/provisorio − 1), tenemos la variación
para todos los meses a ver si es estable o tiene volatilidad»*. El valor
anterior de la fórmula también se toma provisorio de ese momento, así que las
dos puntas se liquidan con números que INDEC todavía puede corregir: esto mide
cuánto se corrigen, para saber si eso importa.

⚠ DE DÓNDE SALE CADA PUNTA.
  · El PROVISORIO es el primero que salió, de `indec_op_revisiones` — la tabla
    que guarda cada valor tal como se leyó en cada foto. Sin ella no existe: el
    .xls de INDEC es siempre la foto de HOY y la corrección no queda en ningún
    lado.
  · El DEFINITIVO es el estado de HOY, de `indec_op_valores`. No se lee de
    `revisiones` a propósito: ahí el definitivo aparece solo si el número
    CAMBIÓ, y el caso más importante es el contrario —el mes que cierra sin que
    le toquen el valor, que es la prueba de que el provisorio servía—. Leyendo
    solo `revisiones` quedaban únicamente los que se movieron y el promedio
    exageraba la volatilidad. (El loader tenía además el bug de no comparar el
    flag: arreglado el 13/09/2026, pero las fotos viejas no se recuperan.)

⚠ NO HAY COLUMNA DE DÍAS. Se podría restar foto de cierre menos foto de
publicación, pero el cierre no se conoce: solo sabemos que pasó entre dos de
nuestras bajadas, y con 4 fotos ese techo es de años. Un número así invita a
leerlo como plazo y no lo es. El plazo se lee de la ventana de provisorios
(REDETERMINACION__DISENO.md §2.1): seis meses.
"""
import sys
from pathlib import Path

# ⚠ La consola de Windows arranca en cp1252 y revienta con una flecha o un
# triángulo de aviso: UnicodeEncodeError en el print, no en la consulta.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # stdout redirigido a algo que no se puede reconfigurar
    pass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE.parent / ".env")

import db  # noqa: E402

CONSULTA = """
with rev as (
  select grupo, codigo, origen, cuadro, periodo,
         (array_agg(indice order by foto) filter (where provisorio))[1] as prov_ind,
         (array_agg(foto   order by foto) filter (where provisorio))[1] as prov_foto
    from indec_op_revisiones
   group by 1,2,3,4,5
)
select r.grupo, r.codigo, r.periodo, r.prov_ind, r.prov_foto,
       v.indice     as hoy_ind,
       v.provisorio as sigue_prov,
       case when v.provisorio then null
            else v.indice / nullif(r.prov_ind, 0) - 1 end as var,
       c.descripcion
  from rev r
  -- join y no left join: si el concepto ya no está en la publicación de hoy no
  -- se puede decir si cerró. Inventarle un definitivo seria peor que omitirlo.
  join indec_op_valores v
    on (v.grupo, v.codigo, v.origen, v.cuadro, v.periodo)
     = (r.grupo, r.codigo, r.origen, r.cuadro, r.periodo)
  left join indec_op_conceptos c
    on (c.grupo, c.codigo, c.origen, c.cuadro) = (r.grupo, r.codigo, r.origen, r.cuadro)
 -- ⚠ descarta los meses que ya estaban cerrados cuando bajamos la primera
 -- foto: de esos no tenemos el provisorio y no hay con qué comparar. Contarlos
 -- como "sin variación" sería inventar el dato.
 where r.prov_ind is not null and v.indice is not null
 order by r.periodo, r.grupo, r.codigo
"""


def _desvio(vs: list[float]) -> float:
    """Desvío estándar a mano: es lo que contesta si la corrección es estable.

    Una media de +0,2 % puede ser treinta meses en +0,2 % o quince en +5 % y
    quince en −4,6 %. Para decidir si el provisorio sirve para liquidar hay que
    ver la dispersión, no el promedio.
    """
    if len(vs) < 2:
        return 0.0
    m = sum(vs) / len(vs)
    return (sum((v - m) ** 2 for v in vs) / (len(vs) - 1)) ** 0.5


def main() -> int:
    args = sys.argv[1:]
    detalle = "--detalle" in args
    solo_abiertos = "--abiertos" in args
    filtro = next((a.split("=", 1)[1] for a in args if a.startswith("--codigo=")), None)

    with db._conectar() as cx, cx.cursor() as cur:
        cur.execute("select foto, count(*) n from indec_op_revisiones group by 1 order by 1")
        fotos = cur.fetchall()
        cur.execute(CONSULTA)
        filas = cur.fetchall()

    if not fotos:
        print("No hay revisiones cargadas todavía. Corré api/cargar_indec_op.py")
        return 1

    print("publicaciones registradas (cada bajada del .xls):")
    for f in fotos:
        print(f"  {f['foto']}  {f['n']:6d} valores")

    if filtro:
        filas = [f for f in filas if f["codigo"] == filtro]

    cerrados = [f for f in filas if not f["sigue_prov"]]
    abiertos = [f for f in filas if f["sigue_prov"]]

    print(f"\n{len(filas)} series-mes salieron provisorias y las seguimos:")
    print(f"  {len(cerrados):5d} ya son definitivas  -> se puede medir la corrección")
    print(f"  {len(abiertos):5d} siguen provisorias  -> todavía pueden moverse")

    if solo_abiertos:
        print("\ntodavía provisorias (el número con el que se liquida hoy):")
        for f in sorted(abiertos, key=lambda f: (f["periodo"], f["grupo"], f["codigo"])):
            print(f"  {f['periodo']} {f['grupo']:15s} {f['codigo']:12s} "
                  f"{(f['descripcion'] or '')[:32]:32s} "
                  f"{float(f['hoy_ind']):12.2f}")
        return 0

    if not cerrados:
        print("\nninguna cerró todavía: no hay variación que medir.")
        return 0

    # ── la pregunta de Juan: la variación mes por mes ──────────────────────
    print("\nprovisorio -> definitivo, MES POR MES  (definitivo/provisorio − 1):")
    print(f"  {'periodo':10s} {'series':>6s} {'=0%':>5s} {'media':>8s} "
          f"{'peor':>8s} {'desvío':>8s}")
    por_mes: dict = {}
    for f in cerrados:
        por_mes.setdefault(f["periodo"], []).append(f)
    for per in sorted(por_mes):
        vs = [float(g["var"]) for g in por_mes[per]]
        # los ratificados sin cambiar: el dato que dice si el provisorio sirve
        quietos = sum(1 for v in vs if abs(v) < 1e-9)
        print(f"  {str(per):10s} {len(vs):6d} {quietos:5d} {sum(vs)/len(vs):+8.2%} "
              f"{max(vs, key=abs):+8.2%} {_desvio(vs):8.2%}")
    todas = [float(f["var"]) for f in cerrados]
    q = sum(1 for v in todas if abs(v) < 1e-9)
    print(f"  {'TOTAL':10s} {len(todas):6d} {q:5d} {sum(todas)/len(todas):+8.2%} "
          f"{max(todas, key=abs):+8.2%} {_desvio(todas):8.2%}")
    print(f"\n  ratificadas sin tocar el valor: {q} de {len(todas)} "
          f"({q / len(todas):.1%})")

    print("\ndónde se concentra la corrección (por grupo):")
    grupos: dict = {}
    for f in cerrados:
        grupos.setdefault(f["grupo"], []).append(float(f["var"]))
    for g, vs in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        movidas = [v for v in vs if abs(v) >= 1e-9]
        print(f"  {g:16s} {len(vs):5d} series · {len(movidas):4d} corregidas · "
              f"media {sum(vs)/len(vs):+.3%} · peor "
              f"{(max(vs, key=abs) if vs else 0):+.2%}")

    if detalle:
        print("\ndetalle (provisorio y definitivo, uno al lado del otro):")
        for f in sorted(cerrados, key=lambda f: -abs(float(f["var"]))):
            if abs(float(f["var"])) < 1e-9:
                continue
            print(f"  {str(f['periodo'])} {f['grupo']:15s} {f['codigo']:12s} "
                  f"{(f['descripcion'] or '')[:30]:30s} "
                  f"prov {float(f['prov_ind']):10.2f} -> def {float(f['hoy_ind']):10.2f} "
                  f"{float(f['var']):+7.3%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

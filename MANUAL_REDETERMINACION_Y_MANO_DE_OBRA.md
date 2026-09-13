# Manual: redeterminación e índices de mano de obra

Los datos están en **`H:\My Drive\web_sibra\indices\`** como CSV (separador `;`,
decimal con punto, UTF-8 con BOM para que Excel los abra bien).

Se regeneran con:

```bash
cd indices && py api/exportar_drive.py
```

> ⚠ **Los CSV son una copia para tener el dato a mano.** La fuente de verdad
> sigue siendo Supabase, que es lo que consume el endpoint de redeterminación.
> Si alguna vez divergen, manda la base. Se reescriben enteros en cada corrida:
> nunca se appendean, justamente para que no aparezca el mismo período dos
> veces con dos valores.

---

## 1 · El índice se pacta por contrato

La orden de venta con el cliente define **un** índice (por ejemplo CAMARCO); la
orden de trabajo con el proveedor define **otro** (por ejemplo UOCRA). No es una
polinómica de insumos: es un índice por contrato, elegido al firmar.

**La regla, en las dos puntas: el índice del MES ANTERIOR.** Un contrato base
abril que se redetermina a agosto se calcula con marzo → julio, porque el índice
del mes que arranca todavía no está publicado cuando arranca.

Esa regla ya está aplicada en el endpoint, así que no hay que aplicarla a mano:

```
GET /api/redet/salto?serie=CAC&columna=COSTO_CONSTRUCCION&base=2026-04&redet=2026-08
```

```json
{ "regla": "indice del mes anterior en las dos puntas",
  "base":  {"periodo": "2026-03", "indice": 19771.2, "provisorio": false},
  "redet": {"periodo": "2026-07", "indice": 21960.7, "provisorio": true},
  "factor": 1.1107418871894472,
  "alguna_punta_provisoria": true,
  "avisos": ["PUNTA DE REDETERMINACION PROVISORIA (2026-07): …"] }
```

`GET /api/redet/series` lista los índices pactables **y hasta qué mes llega cada
uno**. Hay que mirarlo *antes de firmar*: `CONSTRUCCION` está parado en
feb-2026, así que un contrato con ese índice hoy no se puede redeterminar.

> **El índice que se pacta pesa más que el plazo.** Mismo período abril→agosto:
> CAC **+11,07 %**, UOCRA **+21,87 %**. El doble.

---

## 2 · Provisorio y definitivo

Las dos fuentes publican valores que después corrigen, y **la redeterminación se
liquida con el provisorio a propósito** (también el valor anterior se toma
provisorio de ese momento). Esto no es un problema a evitar, es un control a
tener.

| | ventana de provisorios | dónde está la marca |
|---|---|---|
| **CAMARCO (CAC)** | 3-4 meses | `camarco_cac.csv`, columna `provisorio` |
| **INDEC (436 insumos)** | 6 meses | `indec_op_valores.csv`, columna `provisorio` |

**Tres estados, no dos.** `SI` provisorio, `NO` definitivo, **vacío = no lo
sabemos**. Vacío no es definitivo: de las 36 series solo el CAC publica la
distinción. UOCRA no la publica (sus acuerdos son definitivos desde que se
homologan).

### Cuánto se corrigen — medido

De **5.290** series-mes de INDEC ya cerradas, **5.152 (97,4 %) se ratificaron sin
tocarles el valor**. Corrección media +0,00 %, desvío 0,13 %, peor caso +5,20 %.

- **Ni un material se corrigió nunca**: 3.672 series-mes de materiales cerradas,
  cero cambios. Tampoco IPIB, servicios ni equipos.
- Todo el riesgo está en **mano de obra**, donde se corrige **1 de cada 4**.
- Y el golpe está **en el mes más fresco**, que por la regla del mes anterior es
  justo el que se usa: may-22 +5,20 %, feb-24 +4,66 %, nov-25 +4,73 %. Los de
  seis meses atrás, 0,00 %.

**Conclusión operativa:** liquidar con el provisorio está bien. Lo que hay que
hacer es guardar con qué foto se liquidó y controlarlo cuando cierre.
`indec_op_revisiones.csv` guarda cada valor tal como se leyó en cada bajada, así
que un cálculo viejo se puede reproducir y recalcular contra el definitivo:

```bash
py api/revisiones_indec.py            # la variación mes por mes, con desvío
py api/revisiones_indec.py --abiertos # lo que todavía es provisorio
```

---

## 3 · Cuándo se publica cada cosa

Los dos ritmos son opuestos, y conviene tenerlo claro para no esperar un dato
que no va a llegar:

- **CAC: sale 20-24 días DESPUÉS del mes que mide.** Julio-2026 se publicó el
  24/08/2026; junio, el 21/07. Nunca vas a tener el mes corriente.
- **UOCRA: se pacta ANTES, en bloques de 2-3 meses.** El acuerdo del 27/05/2026
  cubre junio-julio-agosto. Sabés dos o tres meses para adelante, pero te
  enterás del bloque recién cuando arranca.

`camarco_acuerdos_salariales.csv` tiene las dos fechas, que **no son la misma
cosa**:

- `fecha_publicacion` — cuándo CAMARCO lo subió. Siempre está.
- `fecha_suscripcion` — cuándo lo firmaron las partes, leída del texto del PDF
  ("a los 19 días del mes de agosto de 2026"). Es el día en que el número se
  pudo saber. Vacía si el PDF es un escaneo o está redactado de otra forma:
  **vacía significa que no se leyó, nunca se rellena con la de publicación.**

---

## 4 · El coeficiente sobre el jornal — esto es el 2,15

CAMARCO publica **«Incidencia de las Cargas Sociales»** desagregada en items, y
uno de ellos es literalmente *Asignación para vestimenta*. Está en
`camarco_cargas_sociales_coeficiente.csv` (el total) y
`camarco_cargas_sociales_items.csv` (renglón por renglón).

**Mano de obra directa, vigencia 1º/07/2026 — Trabajo Técnico Nº 185:**

| | concepto | incidencia % |
|---|---|---:|
| a | Salario por tiempo efectivamente trabajado | 100,00 |
| b | Asistencia Perfecta | 18,00 |
| c | Salarios pagados por tiempos no trabajados, incluida indemnización por causas climáticas | 16,53 |
| d | **Asignación para vestimenta** | 3,61 |
| e | Sueldo Anual Complementario | 11,44 |
| f | Fondo de Cese Laboral e Indemnización por fallecimiento | 16,87 |
| g | *Subtotal liquidado* | *166,45* |
| h | Contribuciones Patronales y Seguro de Vida Colectivo Obligatorio | 39,32 |
| i | A.R.T. | 7,72 |
| **j** | **COSTO TOTAL** | **213,50** |

O sea: el 2,15 que se usaba es **2,1350**. Y la serie es notablemente estable —
215,48 (feb-20) · 215,76 (feb-21) · 213,66 (jul-23) · 213,12 (jun-24) · 213,87
(jun-25) · 213,50 (jul-26).

**Capataces es otro trabajo y otro coeficiente: 148,85 %** (vigencia 1º/09/2026).
Su tabla tiene siete items y conceptos distintos — sueldo por tiempo corrido, sin
asistencia perfecta ni vestimenta. **No se mezclan.**

### Las tres bases de hora — y cuál usar

Nombres de Juan (13/09/2026): *«uno hora oficial si nada, lo que se publica, o
ajustar por hora "camarco" vamos a llamarlo; cuando el subcontrato sea más
exacto vamos a tener que considerar los más parecido a cómo es el recibo de
sueldo»*.

| base | qué es | Oficial, Zona A, ago-2026 | para qué |
|---|---|---:|---|
| **hora oficial** | el básico publicado por UOCRA, tal cual | **$ 6.348,00** | comparar, verificar una factura |
| **hora CAMARCO** | básico × coeficiente de incidencia (2,1350) | **$ 13.552,98** | presupuestar, redeterminar, APU |
| **hora recibo** | la liquidación real del trabajador | *todavía no existe* | subcontrato exacto, costo real por obra |

Las cuatro categorías, agosto-2026 Zona A:

| categoría | hora oficial | hora CAMARCO |
|---|---:|---:|
| Ayudante | 5.399,00 | 11.526,86 |
| Medio Oficial | 5.866,00 | 12.523,91 |
| Oficial | 6.348,00 | 13.552,98 |
| Oficial Especializado | 7.420,00 | 15.841,70 |

### Las horas hábiles ya están adentro del coeficiente

CAMARCO publica su propia distribución del tiempo en el Trabajo completo, y
ancla el 100 % ahí: *«1- Salario por tiempo efectivamente trabajado 100,00 %
(corresponde 1885 horas/año)»*.

| | días/año | horas/año | por quincena |
|---|---:|---:|---:|
| año calendario | 365 | 2.920 | — |
| **lo que la OBRA trabaja** | 262 | **2.098** | ≈ 87,4 h |
| **lo que los OPERARIOS trabajan** | 236 | **1.885** | ≈ 78,5 h |

Del calendario a la obra se descuentan domingos (52), medios sábados (26),
feriados (12) y **13 días de lluvia** (84 días corridos de lluvia/año en
Capital, de los que se estima que el 20 % paraliza la obra). De la obra al
operario, licencia ordinaria (11), inasistencias (3), enfermedad (7), licencias
especiales (1) y accidentes (5).

> ⚠ **LA TRAMPA: no dividas un costo de quincena por las horas trabajadas.** El
> item c del coeficiente (16,53 %) YA ES *«salarios pagados por tiempos no
> trabajados, incluida indemnización por causas climáticas»*. Si además bajás el
> divisor a horas productivas, contás la lluvia dos veces.
>
> Con 10 horas trabajadas: lo correcto es `10 × 6.348 × 2,1350 = $ 135.529,80`.
> Prorratear la quincena entera (88 h = $ 1.192.662) sobre 10 horas da
> **$ 119.266 por hora — inflado 8,8 veces.**

La fórmula es: **`horas efectivamente trabajadas × básico horario × coeficiente`**.
Las horas hábiles sirven para otra cosa: estimar la capacidad de una quincena y
el rendimiento de un APU.

### Qué aportes están y cuáles NO

**SÍ está** — item h, `39,32 %`, desglosado en el Trabajo completo:
`20,4 %` (Régimen Nacional de Jubilaciones y Pensiones, ex-Cajas de Subsidios
Familiares, Fondo Nacional de Empleo, INSSJyP) `+ 6,00 %` (Régimen de Obras
Sociales) `= 26,4 %` aplicado al total de conceptos remuneratorios (148,76 %),
lo que da `39,27 %`, más el Seguro de Vida Colectivo Obligatorio.

**NO está** (verificado por búsqueda en todo el texto del Trabajo 185 — cero
menciones de cada uno). Todo esto va **por encima** del 213,50 %:

- **Las sumas no remunerativas.** Y no son chicas: $67.100 por quincena para un
  Oficial (julio-2026), del orden del 13 % del básico quincenal.
- **El aporte solidario extraordinario** (2 % sobre remuneraciones de no
  afiliados, 04/2026 → 03/2027).
- **La contribución empresaria del 2 %.** Además es imposible que esté: el
  Trabajo 185 se publicó el **03/07/2026** y esa contribución se firmó el
  **30/07/2026** y se homologó el **20/08/2026** (con vigencia retroactiva al
  01/06/2026). Hasta que CAMARCO publique el Trabajo siguiente, el 2 % se suma
  aparte.
- **IERIC.**

**Los aportes del trabajador tampoco están, y corresponde que no estén**:
jubilación, obra social e INSSJP salen del bruto del trabajador. No son costo
del empleador — están adentro del 100.

> Conclusión: **el 2,15 que usabas no estaba de más, estaba de menos.** El
> coeficiente publicado es 2,1350, pero le falta el no remunerativo (~13 %) y el
> 2 % de contribución empresaria.

### Dos advertencias antes de usarlo

1. **El item de ART hay que reemplazarlo por el propio.** CAMARCO usa el
   promedio país de la cuota pactada que releva la Superintendencia de Riesgos
   del Trabajo (5,8 % de la masa salarial a marzo-2026), y el propio PDF avisa
   que *«existe para esta Carga Social una dispersión muy grande entre una
   empresa y otra»*. Es el renglón que más se movió: 6,55 → 6,67 → 6,81 → 7,72.
   Con la alícuota real de la empresa, los otros nueve items sirven tal cual.

2. **Es para PREVISIÓN, no para liquidar un recibo.** La incidencia es un peso
   sobre 100 de salario, útil para presupuestar y para redeterminar. No son las
   retenciones ni las contribuciones que van en un recibo, y la *Asistencia
   Perfecta* del 18 % es un promedio: en un recibo real se gana o no se gana.

La columna `suma_controlada` dice `SI` cuando los items suman el subtotal y el
subtotal más el resto suman el total. **Si alguna vez dice `NO`, el PDF cambió
de formato y el archivo no se puede usar hasta revisarlo.**

---

## 5 · Qué hay de UOCRA, y qué falta

`uocra_jornales.csv` tiene los básicos por categoría y las sumas no
remunerativas. `uocra_adicionales.csv` tiene el aporte solidario (2 %), la
contribución empresarial ($6.000) y el seguro de vida, con su vigencia y el
texto completo del acuerdo.

**Lo que falta, y hay que saberlo antes de liquidar nada:**

- ⚠ **Los jornales son de ZONA A únicamente.** El scraper lee la columna de
  Zona A del ANEXO I. La escala publica todas las zonas: para liquidar fuera de
  Zona A hay que leer las demás.
- ⚠ **La contribución empresaria del 2 % no está cargada.** Se homologó el
  20/08/2026 con vigencia **retroactiva al 01/06/2026**, y toma como base los
  rubros remunerativos normales, habituales y mensuales (Decreto 612/2026).
- **Los pagos «por única vez»** no se capturan: viven en PDFs sueltos del otro
  listado de UOCRA, cada uno con su propia justificación y sin fórmula común.
- **No hay nada que cubra septiembre-2026 en adelante**: ni el feed de acuerdos
  ni nuestra serie. Si aparece un valor de octubre, salió de otra fuente.

---

## 6 · El recibo y el F.931 — la hora recibo

El **Libro de Sueldos Digital** de ARCA es el camino por el que hoy se genera el
F.931, y **ARCA publica su tabla de conceptos en abierto**. Eso convierte "cómo
se arma un recibo" en un mapeo contra una tabla publicada, en vez de una
reconstrucción a partir de blogs. Está en `arca_conceptos_sueldo_931.csv` — 112
conceptos: 48 remunerativos, 46 no remunerativos, 18 descuentos.

Los que hacen falta para liquidar en construcción (columna
`relevante_construccion = SI`):

| código | tipo | concepto |
|---|---|---|
| `110000` | remunerativo | Sueldo — acá va el jornal |
| `110007` | remunerativo | Feriado |
| `120003` | remunerativo | SAC proporcional |
| `130001` / `130002` | remunerativo | Horas extras al 50 % / al 100 % |
| `140000` | remunerativo | Zona desfavorable |
| `160001` | remunerativo | Adicional por antigüedad |
| `160004` | remunerativo | **Adicional por desarraigo** |
| `170001` | remunerativo | **Premio por presentismo** — la asistencia perfecta |
| `170005` | remunerativo | Viáticos sin comprobante |
| `520003` | no remunerativo | **Provisión de ropa de trabajo** — la "vestimenta" de CAMARCO |
| `810000` / `810001` / `810002` | descuento | Sistema previsional 11 % · INSSJyP 3 % · Obra Social 3 % |
| `810004` | descuento | Cuota Sindical — 2 % UOCRA |
| `810005` | descuento | Seguro de Vida |
| `810008` | descuento | Impuesto a las Ganancias |

Para un concepto que la tabla no tiene (la suma no remunerativa del acuerdo
UOCRA, por ejemplo), ARCA deja **rangos de uso libre**: `521000-529999` para
beneficios sociales, `551000-559999` para importes no remunerativos especiales.
Están en el CSV con `uso_libre = SI`.

### Tres cosas que salieron de cruzar fuentes

**1 · El Fondo de Cese Laboral NO pasa por el 931.** No hay código para él en
toda la tabla. Lo más cercano es `520010` *Gratificación por cese laboral* y
`520014` *Indemnización por despido*, que son pagos por **terminar** la
relación, no el depósito mensual. Coincide con la Ley 22.250: el fondo va a una
cuenta a nombre del trabajador (**art. 15**: 12 % el primer año, 8 % desde el
año de antigüedad; **art. 16**: dentro de los primeros 15 días del mes
siguiente) y se prueba con una constancia mensual escrita propia (**art. 29**).

> ⚠ Es un costo real que nunca aparece en el 931. Quien reconcilie costo de
> personal contra el 931 va a estar corto un 12 % u 8 % y va a creer que le
> falta plata.

**2 · El desarraigo es REMUNERATIVO según ARCA** (`160004`). Las guías de
liquidación de UOCRA que circulan lo ponen como no remunerativo. **Manda esta
tabla**, que es contra la que valida el 931.

**3 · El premio asistencia es 20 %, no 18 %.** CAMARCO dice textual: *«el 90 %
de los operarios cobra el premio por asistencia, en consecuencia dicho premio
integra el salario en un 18 %»*. 20 × 0,90 = 18 exacto. El 18 % es un promedio
actuarial; en el recibo se gana o no se gana. **Ésa es la diferencia de fondo
entre la hora CAMARCO y la hora recibo.**

### Y una que evita un doble cómputo

La **contribución diferencial de la Ley 26.494** (2 % el 1º año, 3 % el 2º, 4 %
el 3º, 5 % el 4º — o sea 5 % hoy) **ya está adentro del 39,32 %** de CAMARCO:
figura en la legislación del item 10 (Contribuciones patronales – C.U.S.S.) del
Trabajo 185. **No se suma aparte.**

### Qué falta para la hora recibo

Los porcentajes de los descuentos (11 / 3 / 3 / 2) vienen de fuentes
secundarias que coinciden entre sí, pero **no de una fuente oficial**. Y falta
lo que ninguna búsqueda reemplaza:

- **un recibo real** de la empresa, y
- **un F.931 o el TXT del Libro de Sueldos Digital**, que es texto plano de
  campos fijos.

Con esos dos el mapeo concepto → campo queda con los códigos que la empresa
usa de verdad, y la hora recibo sale medida, no reconstruida. El contador ya
los tiene: presenta el 931 todos los meses.

---

## 7 · Lo que estos archivos NO son

- **No son una liquidación de sueldos.** Para eso hace falta el parte por
  trabajador y por obra (horas, faltas, días de lluvia), las retenciones reales
  y las contribuciones. Es el módulo de mano de obra propia, que todavía no
  existe.
- **No son la polinómica de INDEC en uso.** Los 436 índices por insumo están
  cargados, pero redeterminar todo con ellos es por ahora un **control de
  gestión**: la comparación contra lo que se hace, con valores reales de
  proveedores y de MercadoLibre al lado.
- **No reemplazan el asiento.** Nada de esto crea plata ni imputa un costo.

---

## Archivos

| archivo | qué es | filas |
|---|---|---:|
| `camarco_cac.csv` | indicador CAC mensual, con marca de provisorio | 187 |
| `camarco_cargas_sociales_coeficiente.csv` | el coeficiente total por vigencia | 10 |
| `camarco_cargas_sociales_items.csv` | los renglones que lo componen | 88 |
| `camarco_acuerdos_salariales.csv` | acuerdos con fecha de publicación y de firma | 100 |
| `uocra_jornales.csv` | básicos y no remunerativos por categoría (Zona A) | 73 |
| `uocra_adicionales.csv` | aportes, contribuciones y seguro, con vigencia | 4 |
| `arca_conceptos_sueldo_931.csv` | la tabla oficial de conceptos del F.931 | 112 |
| `indec_op_conceptos.csv` | los 436 índices por insumo, con su código CPC | 436 |
| `indec_op_valores.csv` | el valor de hoy de cada uno, por mes | 56.348 |
| `indec_op_revisiones.csv` | cada valor tal como se leyó en cada bajada | 56.564 |

> ⚠ En `indec_op_*`, **el mismo CPC aparece hasta cuatro veces** (nacional /
> importado × cuadro 2 y 3). La clave es `grupo + codigo + origen + cuadro`, no
> el código solo.

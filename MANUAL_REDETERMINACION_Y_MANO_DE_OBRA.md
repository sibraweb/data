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

## 6 · Lo que estos archivos NO son

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
| `indec_op_conceptos.csv` | los 436 índices por insumo, con su código CPC | 436 |
| `indec_op_valores.csv` | el valor de hoy de cada uno, por mes | 56.348 |
| `indec_op_revisiones.csv` | cada valor tal como se leyó en cada bajada | 56.564 |

> ⚠ En `indec_op_*`, **el mismo CPC aparece hasta cuatro veces** (nacional /
> importado × cuadro 2 y 3). La clave es `grupo + codigo + origen + cuadro`, no
> el código solo.

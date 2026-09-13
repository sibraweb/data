# Actualización de certificados de obra pública — metodología

**Qué contesta este documento:** la página recibe *fecha inicial*, *fecha final* y
*monto*, y devuelve cuánto hay que pagar (o cuánto dan hoy). Acá está, completo,
de dónde sale cada número — para poder defenderlo frente a la contraparte, no
solo para poder calcularlo.

Motor: `api/descuento_certificados.py` · Carga del publicado:
`api/cargar_camarco_certificados.py` · Datos: `datos/` ·
Pantalla: pestaña **Descuento de certificados (BNA)**.

Estado al **11/09/2026**. **Cubre desde el 01/01/2018.**

---

## 1. El encuadre

**Ley 13.064, art. 48.** Ante atraso en el pago de certificados corresponde
«la tasa fijada por el Banco de la Nación Argentina para los descuentos sobre
certificados de obra».

**Decreto 13.477/56, art. 1º.** Es lo que obliga al BNA a hacer conocer esas
tasas. Los préstamos con caución de certificados se instrumentan como adelantos
en cuenta corriente, y los intereses «se perciben por período mensual vencido» —
de ahí sale que la conversión pase por una tasa mensual (§2).

Dos consecuencias que mandan todo lo demás:

- **La tasa la fija el BNA, no CAMARCO.** CAMARCO *compila* la serie. La tasa de
  origen es del BNA y los insumos son públicos.
- **Rige para obra NACIONAL.** Si la obra es provincial o municipal hay que
  confirmar qué tasa fija la ley local o el pliego (§6).

---

## 2. La fórmula

El BNA no capitaliza con la convención bancaria común. Pasa primero por una
tasa **mensual** — porque el interés se percibe por período mensual vencido:

```
TNM   = TNA × 30 / 365                  ← sin redondear
i_d   = (1 + TNM)^(1/30) − 1            ← tasa efectiva diaria
I(t)  = I(t−1) × (1 + i_d)              ← días CALENDARIO

Coeficiente = I(fecha final) / I(fecha inicial)
```

### Por qué no es una tasa más de la pestaña de Mora

`mora.py` hace `i_d = TNA / 365`. Con TNA 30 % eso da 0,0821918 % diario; la del
BNA da 0,0812278 %. Una diezmilésima por día que sobre cuatro años llega a
**10 % del interés**. Por eso son dos pestañas.

### Verificación (fila publicada de CAMARCO, TNA 30 %)

| | valor |
|---|---|
| Índice 28/02 | 168,768895 |
| TNM | 2,465753 % (CAMARCO la muestra redondeada: 2,47 %) |
| i_d | 0,000812278 |
| 168,768895 × (1 + i_d) | **168,905982** |
| Índice 29/02 publicado | **168,905982** ✓ exacto a seis decimales |

Esa fila fija tres cosas: la **TNM va sin redondear** (con 2,47 % daría
168,906216); se **capitaliza por día corrido**, 29/02 incluido; y la
alternativa TNA/365 queda descartada (daría 168,907610).

---

## 3. De dónde sale el número: publicado primero

**CAMARCO publica el índice diario completo, en abierto y sin login.** El archivo
«Evolución histórica de tasas Banco Nación 2018 – Septiembre 2026» vive en la
biblioteca de medios del sitio. Trae, por día y para las dos categorías de
tomador, la TNA, la TNM y el **índice T.E.M.** acumulado.

`api/cargar_camarco_certificados.py` lo descubre (el nombre cambia cada mes), lo
baja, lo parsea y lo carga: **3.174 días, del 01/01/2018 al 09/09/2026, sin un
solo hueco.** Queda en cuatro series: `CERT_BNA_IND_GRANDES`,
`CERT_BNA_IND_MIPYME`, `CERT_BNA_TNA_GRANDES`, `CERT_BNA_TNA_MIPYME`.

**El reparto de fuentes — manda lo nuestro** (Juan, 11/09/2026: *«nosotros
vamos a tener nuestros propios valores, lo de CAMARCO es backtesting nomás»*):

| | Cubre | Rol |
|---|---|---|
| **Nuestro cálculo** | **01/01/2018 → hoy** | **Manda.** El índice lo armamos con nuestra fórmula, desde base 100. |
| **Índice publicado de CAMARCO** | 01/01/2018 → última fecha del PDF | **Backtesting.** 3.174 días de dato contra el cual verificar. |

**La tasa y el índice son dos cosas distintas, y separarlas es lo que permite
tener serie propia completa.** El insumo de cada día es una TNA; el índice es lo
que nosotros hacemos con ella. Para el 94 % de los días la TNA la
*reconstruimos* (serie del BCRA + spread del BNA). Para los 339 días del tramo
TACG no se puede — no hay fórmula — así que la TNA se *releva*. Pero el índice
lo calculamos nosotros en los dos casos, y por eso la serie es nuestra de punta
a punta.

Resultado al 11/09/2026: **3.173 días de capitalización, ningún hueco, ningún
aviso**, y cierra contra el publicado con **0,062 %** en ocho años y medio.

El empalme **re-escala, no concatena**: el índice publicado viene acumulando
desde 1991 (vale 220,93 el 01/01/2018) y la reconstrucción arranca en 100. El
tramo reconstruido se reescala para arrancar donde termina el publicado, y la
pantalla avisa desde qué día el número dejó de ser leído y pasó a ser calculado.

**Qué tan bien cierra la reconstrucción contra el publicado:**

| Período | Reconstruido | Publicado | Diferencia |
|---|---|---|---|
| 06/12/2018 → 09/09/2026 | 111,670770 | 111,601647 | +0,06 % |
| 15/03/2021 → 08/12/2024 | 13,194264 | 13,204635 | −0,08 % |
| 09/12/2024 → 09/09/2026 | 2,054996 | 2,052290 | +0,13 % |
| **28/01/2026 → 09/09/2026** | 1,215536 | 1,215536 | **0,00 %** |

---

## 4. Los regímenes

Cada tramo dice sobre qué serie del BCRA se para, cuánto spread le suma el BNA y
con cuántos días hábiles de atraso se lee. **Los diez regímenes están confirmados
contra las notas al pie del archivo de CAMARCO** (notas 1 a 10), que citan norma
y fecha. La primera fila no es un régimen: es el tramo anterior a que hubiera
regla.

| Desde | Hasta | Base | No MiPyME | MiPyME | Nota |
|---|---|---|---|---|---|
| 01/01/2018 | 22/05/2018 | **Cartera General (TACG)** | *sin regla publicada* | *sin regla publicada* | — |
| 23/05/2018 | 05/12/2018 | **Cartera General (TACG)** | + 3,00 | TACG | (1) |
| 06/12/2018 | 25/08/2019 | BADLAR privados | **+ 28,00** | + 25,00 | (2) |
| 26/08/2019 | 14/03/2021 | BADLAR privados | **+ 23,00** | + 20,00 | (3) |
| 15/03/2021 | 08/12/2024 | BADLAR privados | **+ 10,00** | + 5,00 | (4) |
| 09/12/2024 | 19/08/2025 | TAMAR privados | **+ 7,00** | + 2,00 | (5) |
| 20/08/2025 | 30/09/2025 | TAMAR privados | **+ 9,00** | + 7,00 | (6) |
| 01/10/2025 | 19/11/2025 | TAMAR privados | **+ 19,00** | + 17,00 | (7) |
| 20/11/2025 | 02/12/2025 | TAMAR privados | **+ 17,00** | + 15,00 | (8) |
| 03/12/2025 | 27/01/2026 | TAMAR privados | **+ 15,00** | + 13,00 | (9) |
| 28/01/2026 | hoy | TAMAR privados | **+ 6,50** | + 6,00 | (10) |

Todos con **5 días hábiles de desfasaje**: la tasa se lee 5 hábiles antes del
inicio del período. Los hábiles salen de las fechas que la serie del BCRA trae
(el BCRA no publica días no hábiles), así que no hace falta un calendario de
feriados. El índice en cambio corre por **días calendario**: sábados, domingos y
feriados capitalizan con la última tasa vigente.

> ⚠ **Esto corrigió un error real.** Hasta el 11/09/2026 el sistema trataba
> 09/12/2024 → 27/01/2026 como un solo tramo al + 7,00. Son cinco regímenes, y
> entre octubre y diciembre de 2025 el spread real fue + 19,00, + 17,00 y
> + 15,00. Cualquier cálculo hecho antes de esa fecha que cruce ese período está
> corto.

### La TACG no se reconstruye

Del **01/01/2018 al 05/12/2018** la base es la **Tasa Activa de Cartera General
del BNA**. La TACG **no se arma con una fórmula**: la fija el propio banco para
su cartera general y la publica porque el decreto 13.477/56 la obliga. Es la
misma «tasa activa cartera general nominal anual vencida a 30 días del Banco de
la Nación» que usan los juzgados.

Se probaron **siete series del BCRA** contra esos 197 días buscando un spread
constante. Ninguna la explica:

| Serie BCRA | Desvío |
|---|---|
| TM20 | 9,50 |
| BADLAR total bancos | 9,80 |
| BADLAR bancos privados | 10,00 |
| Préstamos personales | 10,16 |
| Depósitos a plazo fijo 30 d | 10,27 |
| Adelantos en cta. cte. | 11,75 |

Un desvío de ~10 p.p. significa que no hay ningún spread fijo que sirva. Para ese
tramo **la única fuente posible es el índice publicado** — que lo cubre.

Dato lateral útil: como en esa ventana **MiPyME = TACG exacto**, la columna
MiPyME del archivo de CAMARCO *es* la serie TACG diaria.

### Antes del 23/05/2018 no había regla

Hasta esa fecha la brecha entre las dos columnas es errática — 8,00 · 0,00 ·
−1,50 · −1,00 · −4,50 — y MiPyME llegaba a estar **más cara** que Grandes
Inversores. Desde el 24/05/2018 la brecha es exactamente + 3,00 y no se vuelve a
mover hasta el cambio de régimen. El índice publicado cubre igual ese tramo; lo
que no hay es una regla que lo describa.

---

## 5. Con y sin interés compuesto

**Las dos lecturas usan la misma tasa diaria `i_d`.** La única diferencia es que
una la multiplica día a día y la otra la suma:

```
compuesto = Π (1 + i_d)          ← el índice del BNA, el método de CAMARCO
simple    = 1 + Σ i_d            ← la misma tasa, sumada
```

La página muestra **las dos, del mismo tamaño, siempre**. Antes había un botón
para elegir una. Cuál corresponde lo dice el pliego, y con un botón el que mira
la pantalla ve un número sin enterarse de que existía el otro.

### Cuánto separa a las dos · $ 100.000.000, 01/01/2018 → 09/09/2026

| | Coeficiente | Total |
|---|---|---|
| **Compuesto** | 161,519904 | $ 16.151.990.431 |
| **Simple** | 6,088796 | $ 608.879.582 |
| **Diferencia** | | **+ 2.552,7 %** |

Sobre ocho años y medio el compuesto da **veintiséis veces** el simple. Elegir
mal esta lectura pesa muchísimo más que cualquier otra decisión del cálculo.

Coeficientes publicados de referencia (Grandes Inversores → MiPyME):

| Desde | → 09/09/2026 | Grandes | MiPyME |
|---|---|---|---|
| 01/01/2018 | | 161,519904 | 116,414122 |
| 01/06/2018 | | 144,819520 | 107,085827 |

> ⚠ **La columna del tomador no es un detalle.** Al 09/09/2026 el índice de
> Grandes Inversores vale 43.756 y el de MiPyME 25.719. Elegir mal no da un
> número parecido: da otro.

---

### El cálculo paso a paso, sobre 3 días

Del **01/09/2026 al 04/09/2026**, sobre **$ 10.000.000**. Tres días de
capitalización (el último día se cobra, no capitaliza).

| Fecha | TNA % | TNM % | i_d % | Índice al inicio del día |
|---|---|---|---|---|
| 01/09/2026 | 31,750 | 2,6096 | 0,0859076 | 100,00000000 |
| 02/09/2026 | 31,625 | 2,5993 | 0,0855735 | 100,08590756 |
| 03/09/2026 | 31,688 | 2,6045 | 0,0857405 | 100,17155457 |
| 04/09/2026 | 31,125 | 2,5582 | 0,0842369 | **100,25744219** |

Cada línea sale de la anterior con la fórmula del §2. Por ejemplo, el índice del
02/09:

```
TNA 31,750  →  TNM = 31,750 × 30/365       = 2,6095890 %
            →  i_d = (1+0,026095890)^(1/30) − 1 = 0,000859076
            →  100,00000000 × (1 + 0,000859076) = 100,08590756
```

**Las dos lecturas, sobre la misma tasa diaria:**

```
COMPUESTO   Π (1 + i_d) = 1,00085908 × 1,00085574 × 1,00085741 = 1,00257442
SIMPLE      1 + Σ i_d   = 1 + 0,00085908 + 0,00085574 + 0,00085741 = 1,00257222
```

| | Coeficiente | Interés sobre $ 10.000.000 |
|---|---|---|
| **Compuesto** | 1,00257442 | $ 25.744,22 |
| **Simple** | 1,00257222 | $ 25.722,16 |
| **Diferencia** | 0,00000221 | **$ 22,06** |

**Y acá está el punto.** Sobre 3 días las dos lecturas difieren en 22 pesos
sobre 10 millones: nada. Sobre los 3.173 días que van de enero de 2018 a hoy,
difieren en **veintiséis veces** (§5). No es que una fórmula sea "más agresiva"
que la otra — es la misma tasa. Lo que crece no es la tasa: es el efecto de
multiplicar en vez de sumar, y ese efecto es invisible en el plazo corto y
brutal en el largo. Por eso la discusión no se puede zanjar mirando un ejemplo
de tres días, y por eso la pantalla muestra las dos.

---

## 6. Mora y descuento no son el mismo número al revés

- **Mora** (*me pagaron tarde*): el certificado vale el monto HOY. Se multiplica.
- **Descuento** (*cobrar antes*): vale el monto EN LA FECHA FINAL y se quiere
  saber cuánto dan hoy. Se divide.

Sobre el mismo coeficiente, **descontar da menos que la mora**.

---

## 7. Lo que quedó cerrado, y lo que no

### Cerrado

- ✅ **El encuadre legal**: Ley 13.064 art. 48 + decreto 13.477/56 art. 1º.
- ✅ **Los diez regímenes**, con fecha, spread MiPyME y no-MiPyME, y nota de
  origen. Ya no queda ningún tramo «relevado pero sin confirmar».
- ✅ **Bancos privados vs. total bancos.** Contrastando 4.390 días de TNA
  publicada contra la API del BCRA: **BADLAR privados (7) reproduce el 99,0 %** y
  **TAMAR privados (44) el 96,2 %**; total bancos (138 y 135) dan 1,0 % y 6,7 %.
  Descartado.
- ✅ **Valor puntual vs. promedio de 5 hábiles.** La TNA publicada cambia casi
  todos los días hábiles (1.285 tramos de un solo día sobre 3.174): el «período»
  es diario, como se venía calculando.
- ✅ **El cambio de base del índice.** No aplica: el publicado es una sola serie
  continua 2018 → 2026, y se usa por cociente.

### Abierto

1. **Jurisdicción.** El art. 48 rige obra nacional. Provincial o municipal:
   confirmar ley local o pliego.
2. **Que el PDF siga donde está.** Hoy CAMARCO lo publica sin login y el
   cargador lo descubre solo. Si lo mueven detrás de socios, el cargador falla
   *bajando* (no autenticando) y el mensaje lo dice. La reconstrucción queda como
   respaldo para todo salvo 01/01/2018 → 05/12/2018.
3. **Corrección de serie.** La carga es append-only: no pisa un valor ya
   cargado. CAMARCO ya corrigió la serie una vez (nota del 06.12.2018). Si vuelve
   a pasar, recargar no trae la corrección: hay que borrar el rango y cargarlo de
   nuevo.

---

## 8. Qué NO hace el motor, a propósito

- **No inventa tasas.** Día sin fuente = día que no capitaliza, marcado y con
  aviso. Un número calculado con una regla supuesta es peor que no tener número,
  porque después nadie se acuerda de que era supuesta.
- **No redondea la TNM** (§2). Tampoco guarda la TNM ni la tasa diaria del PDF:
  las deriva de la TNA, que sí trae los decimales necesarios.
- **No resalta el cambio de tasa, resalta el cambio de régimen.** La TAMAR se
  mueve casi todos los días; lo auditable es el día en que el BNA cambió la regla.
- **No esconde el empalme.** Cuando el número deja de ser leído y pasa a ser
  calculado, lo dice con la fecha.

---

## 9. Las fuentes, y en qué orden mandan

Todos verificados el 11/09/2026. Ninguno pide login.

### 1 · Boletín Oficial — la fuente primaria

El BNA publica cada cambio de tasa acá, en cumplimiento del decreto 13.477/56.
El texto de estos avisos es, palabra por palabra, el que CAMARCO reproduce en sus
notas al pie: **CAMARCO transcribe el Boletín.**

- [Aviso del 12/01/2026](https://www.boletinoficial.gob.ar/detalleAviso/primera/337374/20260112)
  — TAMAR + 13 (MiPyME) / + 15 desde el 03/12/2025. ✓ coincide con el tramo (9).
- [Aviso del 02/01/2024](https://www.boletinoficial.gob.ar/detalleAviso/primera/301519/20240102)
  — BADLAR + 5 (MiPyME) / + 10 desde el 15/03/2021. ✓ coincide con el tramo (4).
- [Búsqueda avanzada](https://www.boletinoficial.gob.ar/busquedaAvanzada/primera)
  — para los demás: buscar «caución de certificados de obras».

### 2 · CAMARCO — el compilador

No es la fuente de la tasa: arma la serie diaria a partir de los avisos del BNA y
de las series del BCRA. Lo que aporta, y que no está en ningún otro lado, es el
**índice T.E.M. acumulado** día por día.

- [Indicadores · Tasas](https://www.camarco.org.ar/categorias_indicadores/tasas/)
- [Evolución histórica 2018 – septiembre 2026](https://www.camarco.org.ar/indicador/evolucion-historica-tasas-banco-nacion-2018-septiembre-2026/)
- [El PDF con la serie completa](https://www.camarco.org.ar/wp-content/uploads/2026/08/Evolucion-Historica-Tasas-Banco-Nacion-2018-Septiembre-2026-1.pdf) — 107 páginas, una por mes.
- [API de medios](https://www.camarco.org.ar/wp-json/wp/v2/media?search=Tasas%20Banco%20Nacion)
  — así lo encuentra el cargador, porque el nombre del archivo cambia cada mes.

⚠ **Esta base se releva pero NO se publica** (Juan, 11/09/2026). De CAMARCO sale
publicado únicamente el índice de costo de construcción, que ya se venía
publicando. Ver el candado escrito sobre `RESUMEN_SERIES` en `api/server.py`.

### 3 · BCRA — las series base

- [API de estadísticas monetarias](https://api.bcra.gob.ar/estadisticas/v4.0/monetarias) — sin auth y sin costo.
- [Variable 7 · BADLAR bancos privados](https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/7)
- [Variable 44 · TAMAR bancos privados](https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/44)
- [Principales variables](https://www.bcra.gob.ar/PublicacionesEstadisticas/Principales_variables.asp) — la vista web de lo mismo.

Las de «bancos públicos y privados» son la **138** y la **135**. Están descartadas
(§7), pero conviene tenerlas a mano por si hay que volver a probar.

### 4 · La norma

- [Ley 13.064 de Obras Públicas](https://servicios.infoleg.gob.ar/infolegInternet/anexos/35000-39999/38542/texact.htm)
  (Infoleg, texto actualizado) — el art. 48 es el que manda.
- [BNA · Información al usuario financiero](https://www.bna.com.ar/Home/InformacionAlUsuarioFinanciero)
  — los niveles de tasa vigentes, adonde remiten los propios avisos.

**El decreto 13.477/56** se cita en cada aviso del BNA pero no aparece en Infoleg
con texto completo. Su contenido operativo — que los préstamos con caución de
certificados se instrumentan como adelantos en cuenta corriente con intereses
percibidos por período mensual vencido — está transcripto en los avisos del
Boletín enlazados arriba, que sirven como constancia.

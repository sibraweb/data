// ═══════════════════════════════════════════════════════════════════════════
//  sibra-indices-api.js — las rutas de api/server.py, contra Supabase.
//
//  Cada función de acá tiene su gemela en Python y devuelve EXACTAMENTE la
//  misma forma. La referencia manda: si cambia el cálculo en Python, cambia
//  acá. Al lado de cada una está el archivo/línea que replica, para que la
//  próxima vez se pueda comparar sin adivinar.
//
//  ⚠ DOS IMPLEMENTACIONES DE LA MISMA CUENTA. Es el precio de que la página
//  pública sea un estático: no hay dónde correr el Python. Están verificadas
//  una contra otra (ver VERIFICACION.md) y conviene volver a correr esa
//  comparación cada vez que se toque la matemática de cualquiera de los dos
//  lados.
// ═══════════════════════════════════════════════════════════════════════════
const SbIndices = (() => {

  // ── Config espejada de api/server.py:61-160 ──────────────────────────────
  const SERIES = {
    cer: ['CER', 'VALOR'], uva: ['UVA', 'VALOR'], uvi: ['UVI', 'VALOR'], icl: ['ICL', 'VALOR'],
    inflacion_indec: ['INFLACION_INDEC', 'VALOR'],
    badlar: ['BADLAR', 'VALOR'], tamar: ['TAMAR', 'VALOR'], baibar: ['BAIBAR', 'VALOR'],
    depositos_30d: ['DEPOSITOS_30D', 'VALOR'], adelantos_cta_cte: ['ADELANTOS_CTA_CTE', 'VALOR'],
    prestamos_personales: ['PRESTAMOS_PERSONALES', 'VALOR'], tim: ['TIM', 'VALOR'],
    riesgo_pais: ['RIESGO_PAIS', 'VALOR'], merval: ['MERVAL', 'VALOR'],
    ripte: ['RIPTE', 'RIPTE'], uocra: ['UOCRA', 'OFICIAL'],
    construccion: ['CONSTRUCCION', 'INDICE_GENERAL'], cac: ['CAC', 'COSTO_CONSTRUCCION'],
    salarios: ['SALARIOS', 'INDICE_TOTAL'],
    icc_caba: ['ICC_CABA', 'GENERAL'], icc_buenos_aires: ['ICC_BUENOS_AIRES', 'GENERAL'],
    icc_cordoba: ['ICC_CORDOBA', 'GENERAL'], icc_santa_fe: ['ICC_SANTA_FE', 'GENERAL'],
    alquiler_caba: ['ALQUILER_CABA', 'PROMEDIO'],
  };

  const MULTI = {
    construccion: ['INDICE_GENERAL', 'MATERIALES', 'MANO_DE_OBRA', 'PROVISIONES'],
    cac: ['COSTO_CONSTRUCCION', 'MATERIALES', 'MANO_DE_OBRA'],
    uocra: ['OFICIAL_ESPECIALIZADO', 'OFICIAL', 'MEDIO_OFICIAL', 'AYUDANTE', 'SERENO'],
    salarios: ['PRIVADO_REGISTRADO', 'PUBLICO', 'TOTAL_REGISTRADO', 'NO_REGISTRADO', 'INDICE_TOTAL'],
    icc_caba: ['GENERAL', 'MATERIALES', 'MANO_DE_OBRA', 'GASTOS'],
    icc_buenos_aires: ['GENERAL', 'MATERIALES', 'MANO_DE_OBRA', 'GASTOS'],
    icc_cordoba: ['GENERAL', 'MATERIALES', 'MANO_DE_OBRA', 'GASTOS'],
    icc_santa_fe: ['GENERAL', 'MATERIALES', 'MANO_DE_OBRA', 'GASTOS'],
    alquiler_caba: ['PROMEDIO', 'PRECIO_2_AMBIENTES', 'PRECIO_3_AMBIENTES'],
    caucion: ['TASA_1D', 'TASA_7D', 'TASA_14D', 'TASA_30D'],
    cheques: ['AVALADO_CORTO', 'GARANTIZADO_CORTO', 'NO_GARANTIZADO_CORTO'],
    pagares: ['AVALADO_CORTO', 'GARANTIZADO_CORTO', 'NO_GARANTIZADO_CORTO',
              'AVALADO_CORTO_USD', 'GARANTIZADO_CORTO_USD', 'NO_GARANTIZADO_CORTO_USD',
              'AVALADO_CORTO_DL', 'GARANTIZADO_CORTO_DL', 'NO_GARANTIZADO_CORTO_DL'],
  };
  const MULTI_TAB = {
    construccion: 'CONSTRUCCION', cac: 'CAC', uocra: 'UOCRA', salarios: 'SALARIOS',
    icc_caba: 'ICC_CABA', icc_buenos_aires: 'ICC_BUENOS_AIRES', icc_cordoba: 'ICC_CORDOBA',
    icc_santa_fe: 'ICC_SANTA_FE', alquiler_caba: 'ALQUILER_CABA', caucion: 'CAUCION',
    cheques: 'CHEQUES', pagares: 'PAGARES',
  };

  const DOLAR_TAB = 'DOLAR';
  const DOLAR_COLUMNAS = {
    dolar_oficial: 'OFICIAL_VENTA', dolar_blue: 'BLUE_VENTA', dolar_mep: 'MEP_VENTA',
    dolar_ccl: 'CCL_VENTA', dolar_mayorista: 'MAYORISTA_VENTA',
  };

  // Tabs de una sola columna en series_valores (columna = '_'), server.py:224
  const SIMPLES = new Set(['CER', 'UVA', 'UVI', 'ICL', 'INFLACION_INDEC', 'BADLAR', 'TAMAR',
    'BAIBAR', 'DEPOSITOS_30D', 'ADELANTOS_CTA_CTE', 'PRESTAMOS_PERSONALES', 'TIM',
    'RIESGO_PAIS', 'MERVAL']);

  const RESUMEN_SERIES = [
    ['UOCRA Oficial', 'uocra'], ['RIPTE', 'ripte'], ['Dólar oficial', 'dolar:dolar_oficial'],
    ['Dólar blue', 'dolar:dolar_blue'], ['Dólar MEP', 'dolar:dolar_mep'], ['CER', 'cer'],
    ['UVA', 'uva'], ['UVI', 'uvi'], ['ICL (alquileres)', 'icl'], ['IPC (INDEC, índice)', 'ipc_nivel'],
    ['CAMARCO costo construcción', 'cac:COSTO_CONSTRUCCION'], ['CAMARCO materiales', 'cac:MATERIALES'],
    ['CAMARCO mano de obra', 'cac:MANO_DE_OBRA'],
    ['Construcción general (APYMECO)', 'construccion:INDICE_GENERAL'],
    ['Índice de Salarios INDEC', 'salarios:INDICE_TOTAL'],
    ['ICC Buenos Aires (costo construcción)', 'icc_buenos_aires:GENERAL'],
    ['Alquiler CABA (promedio, fuente 2013-2019)', 'alquiler_caba:PROMEDIO'],
    ['Riesgo país', 'riesgo_pais'], ['MERVAL', 'merval'],
    ['Caución 1 día', 'caucion:TASA_1D'], ['Caución 7 días', 'caucion:TASA_7D'],
    ['Caución 30 días', 'caucion:TASA_30D'],
  ];

  const SEGMENTOS_CARD = [['AVALADO', 'Avalado'], ['GARANTIZADO', 'Garantizado'],
                          ['NO_GARANTIZADO', 'No garantizado']];
  const MONEDAS_CARD = [['', 'Pesos'], ['_USD', 'Dólares'], ['_DL', 'Dólar linked']];
  const TASAS_BCRA = [
    ['badlar', 'BADLAR (plazo fijo mayorista)'], ['baibar', 'BAIBAR (interbancaria)'],
    ['tamar', 'TAMAR (mayorista, plazos largos)'], ['depositos_30d', 'Plazo fijo 30 días (minorista)'],
    ['adelantos_cta_cte', 'Adelantos en cuenta corriente'], ['prestamos_personales', 'Préstamos personales'],
  ];
  const PROYECTABLES = new Set(['uocra', 'construccion', 'ripte']);

  // ── Fechas: todo en 'YYYY-MM-DD' y comparado como texto ──────────────────
  // Ordenar y comparar fechas ISO como strings da el mismo resultado que como
  // fechas, y esquiva de raíz los corrimientos de zona horaria que tiene
  // `new Date('2026-09-04')` según el navegador.
  const hoyISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const aUTC = s => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
  const iso = ms => new Date(ms).toISOString().slice(0, 10);
  const diasEntre = (a, b) => Math.round((aUTC(b) - aUTC(a)) / 86400000);
  const menosDias = (s, n) => iso(aUTC(s) - n * 86400000);
  const menosAnios = (s, n) => `${String(+s.slice(0, 4) - n).padStart(4, '0')}${s.slice(4)}`;
  const finMesAnterior = s => iso(aUTC(`${s.slice(0, 7)}-01`) - 86400000);

  // ── Lectura de series (espejo de api/db.py:75-117) ───────────────────────
  const cache = new Map();
  const conCache = (clave, fn) => {
    if (!cache.has(clave)) cache.set(clave, fn().catch(e => { cache.delete(clave); throw e; }));
    return cache.get(clave);
  };

  // Serie simple -> [{FECHA, VALOR}]; serie ancha -> una fila por fecha con
  // todas sus columnas como llaves (misma forma que devolvía Sheets).
  function leer(tab) {
    return conCache('tab:' + tab, async () => {
      const filas = await SibraSB.selectAll(
        `series_valores?select=fecha,columna,valor&serie=eq.${tab}&order=fecha.asc`);
      if (SIMPLES.has(tab)) {
        return filas.map(f => ({ FECHA: f.fecha, VALOR: f.valor === null ? null : Number(f.valor) }));
      }
      const porFecha = new Map();
      for (const f of filas) {
        if (!porFecha.has(f.fecha)) porFecha.set(f.fecha, { FECHA: f.fecha });
        porFecha.get(f.fecha)[f.columna] = f.valor === null ? null : Number(f.valor);
      }
      return [...porFecha.keys()].sort().map(k => porFecha.get(k));
    });
  }

  // Último valor no vacío de UNA columna, sin bajarse la serie entera.
  async function ultimoDe(tab, columna, hastaFecha) {
    const col = SIMPLES.has(tab) ? '_' : columna;
    const tope = hastaFecha || hoyISO();
    const { filas } = await SibraSB.rest(
      `series_valores?select=fecha,valor&serie=eq.${tab}&columna=eq.${encodeURIComponent(col)}` +
      `&valor=not.is.null&fecha=lte.${tope}&order=fecha.desc&limit=1`);
    return filas.length ? { fecha: filas[0].fecha, valor: Number(filas[0].valor) } : null;
  }

  // ── Materiales (espejo de server.py:_cotizaciones_material) ─────────────
  // Desde el 06/09 esto es UNA sola tabla: `cotizaciones` de Obra, con el
  // histórico viejo adentro. Antes se ensamblaba con la Sheet del Drive, que
  // un estático no puede leer — por eso esta pestaña era la única que no
  // andaba en la página publicada.
  const MATERIALES_CURADOS = {
    '23': ['CEMENTO PORTLAND X 25 KG. (LOMA NEGRA)-25',
           'HIERRO Aº TORS.Ø 10-BR X 12MT.',
           'LADRILLO HUECO DE 1º 18X18X25-5'],
  };
  const PROVEEDORES_NO_MATERIALES = new Set(['209']);   // UOCRA es ficticio
  const INDICES_MATERIALES = {
    hierro: ['23', 'HIERRO Aº TORS.Ø 10-BR X 12MT.'],
    cemento: ['23', 'CEMENTO PORTLAND X 25 KG. (LOMA NEGRA)-25'],
    ladrillo: ['23', 'LADRILLO HUECO DE 1º 18X18X25-5'],
  };

  function leerCotizaciones(idProveedor) {
    return conCache('cot:' + idProveedor, async () => {
      const filas = await SibraSB.selectAll(
        `cotizaciones?select=descripcion,fecha,precio&id_proveedor=eq.${encodeURIComponent(idProveedor)}` +
        `&fecha=neq.&precio=neq.&order=fecha.asc`);
      const out = [];
      for (const f of filas) {
        // Las columnas son `text` (la tabla viene de una planilla): un precio
        // que no es número se descarta, no se toma como cero.
        const precio = Number(String(f.precio).replace(',', '.'));
        if (!Number.isFinite(precio)) continue;
        out.push({ ID_PROVEEDOR: idProveedor, DESCRIPCION: f.descripcion,
                   FECHA: String(f.fecha).slice(0, 10), PRECIO: precio });
      }
      return out;
    });
  }

  // {id: nombre} de los que tienen precios. Se le pregunta a la tabla por el
  // mismo motivo que en el server: la lista escrita a mano se desincronizó de
  // los ids de Obra y la pestaña quedó pidiendo proveedores inexistentes.
  function proveedoresMateriales() {
    return conCache('cot:proveedores', async () => {
      const filas = await SibraSB.selectAll(
        'cotizaciones?select=id_proveedor,proveedor&id_proveedor=neq.');
      const nombres = new Map(), cuenta = new Map();
      for (const f of filas) {
        if (PROVEEDORES_NO_MATERIALES.has(f.id_proveedor)) continue;
        if (f.proveedor) nombres.set(f.id_proveedor, f.proveedor);
        cuenta.set(f.id_proveedor, (cuenta.get(f.id_proveedor) || 0) + 1);
      }
      const orden = [...cuenta.keys()].sort((a, b) => cuenta.get(b) - cuenta.get(a));
      return Object.fromEntries(orden.map(id => [id, nombres.get(id) || id]));
    });
  }

  async function cotizacionesMaterial(idProveedor, descripcion) {
    const filas = await leerCotizaciones(idProveedor);
    return descripcion ? filas.filter(r => r.DESCRIPCION === descripcion) : filas;
  }

  function leerRem(tipo) {
    return conCache('rem:' + tipo, async () => {
      const filas = await SibraSB.selectAll(
        `rem_forecast?select=*&tipo=eq.${tipo}&order=fecha_pronostico.asc,periodo.asc`);
      return filas.map(r => ({
        CLAVE: `${r.fecha_pronostico}|${r.periodo}`,
        FECHA_PRONOSTICO: r.fecha_pronostico, PERIODO: r.periodo,
        MEDIANA: r.mediana === null ? null : Number(r.mediana),
        PROMEDIO: r.promedio === null ? null : Number(r.promedio),
        DESVIO: r.desvio === null ? null : Number(r.desvio),
        MAXIMO: r.maximo === null ? null : Number(r.maximo),
        MINIMO: r.minimo === null ? null : Number(r.minimo),
        PERCENTIL_90: r.percentil_90 === null ? null : Number(r.percentil_90),
      }));
    });
  }

  // ── Resolución de familias (espejo de server.py:746 _resolver_familia) ───
  const redondear = (v, n) => { const f = 10 ** n; return Math.round((v + Number.EPSILON) * f) / f; };

  // IPC solo trae la variación % mensual: para usarlo como nivel hay que
  // encadenarlo (base 100 en el primer punto) — server.py:709
  function construirIndiceNivel(pcts, fechaCol, valorCol, base = 100) {
    let nivel = base;
    const salida = [];
    for (const r of [...pcts].sort((a, b) => String(a[fechaCol]).localeCompare(String(b[fechaCol])))) {
      const v = r[valorCol];
      if (v === null || v === undefined || v === '') continue;
      nivel *= 1 + Number(v) / 100;
      salida.push({ [fechaCol]: r[fechaCol], [valorCol]: redondear(nivel, 4) });
    }
    return salida;
  }

  async function resolverFamilia(familia, item) {
    if (familia === 'ipc_nivel') {
      const pcts = await leer('INFLACION_INDEC');
      return { records: construirIndiceNivel(pcts, 'FECHA', 'VALOR'), fechaCol: 'FECHA', valorCol: 'VALOR' };
    }
    if (SERIES[familia]) {
      const [tab, col] = SERIES[familia];
      return { records: await leer(tab), fechaCol: 'FECHA', valorCol: col };
    }
    if (familia.includes(':')) {
      const i = familia.indexOf(':');
      const tipo = familia.slice(0, i), sub = familia.slice(i + 1);
      if (MULTI[tipo]) {
        const col = MULTI[tipo].includes(sub) ? sub : MULTI[tipo][0];
        return { records: await leer(MULTI_TAB[tipo]), fechaCol: 'FECHA', valorCol: col };
      }
      if (tipo === 'dolar') {
        const col = DOLAR_COLUMNAS[sub];
        if (!col) return null;
        return { records: await leer(DOLAR_TAB), fechaCol: 'FECHA', valorCol: col };
      }
      if (tipo === 'mat') {
        return { records: await cotizacionesMaterial(sub, item), fechaCol: 'FECHA', valorCol: 'PRECIO' };
      }
    }
    return null;
  }

  // Igual que resolverFamilia pero SIN bajar la serie: solo dice de qué tab y
  // columna sale. Lo usa la variación entre dos fechas, que necesita dos
  // puntos y no la serie entera. `null` = hay que resolverla completa.
  function ubicarFamilia(familia) {
    if (SERIES[familia]) return { tab: SERIES[familia][0], columna: SERIES[familia][1] };
    if (familia.includes(':')) {
      const i = familia.indexOf(':');
      const tipo = familia.slice(0, i), sub = familia.slice(i + 1);
      if (MULTI[tipo]) return { tab: MULTI_TAB[tipo], columna: MULTI[tipo].includes(sub) ? sub : MULTI[tipo][0] };
      if (tipo === 'dolar' && DOLAR_COLUMNAS[sub]) return { tab: DOLAR_TAB, columna: DOLAR_COLUMNAS[sub] };
    }
    return null;   // ipc_nivel (derivada) y mat: no tienen atajo
  }

  async function serieIndice(nombre) {
    if (nombre === 'cer' || nombre === 'uva') {
      const [tab, col] = SERIES[nombre];
      return { records: await leer(tab), fechaCol: 'FECHA', valorCol: col };
    }
    if (nombre === 'ipc') return resolverFamilia('ipc_nivel');
    if (DOLAR_COLUMNAS[nombre]) return { records: await leer(DOLAR_TAB), fechaCol: 'FECHA', valorCol: DOLAR_COLUMNAS[nombre] };
    if (INDICES_MATERIALES[nombre]) {
      const [idProv, descripcion] = INDICES_MATERIALES[nombre];
      return { records: await cotizacionesMaterial(idProv, descripcion), fechaCol: 'FECHA', valorCol: 'PRECIO' };
    }
    return resolverFamilia(nombre);
  }

  // ── Matemática (espejo de api/ajuste.py y api/resumen.py) ────────────────
  // _to_df: numérico, ordenado y SIN puntos futuros — CER y otras del BCRA se
  // publican con proyección hasta el 15 del mes siguiente y no son "lo último
  // disponible" (ajuste.py:19 / resumen.py:18).
  function aSerie(records, fechaCol, valorCol) {
    const tope = hoyISO();
    return records
      .map(r => ({ fecha: String(r[fechaCol] || '').slice(0, 10), valor: Number(r[valorCol]) }))
      .filter(p => p.fecha && Number.isFinite(p.valor) && p.fecha <= tope)
      .sort((a, b) => a.fecha.localeCompare(b.fecha));
  }

  const enOAntes = (serie, fecha) => {
    let hit = null;
    for (const p of serie) { if (p.fecha <= fecha) hit = p; else break; }
    return hit;
  };

  // merge_asof(direction="nearest") — ajuste.py:63
  function asofNearest(serie, fecha) {
    if (!serie.length) return null;
    let lo = 0, hi = serie.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (serie[mid].fecha < fecha) lo = mid + 1; else hi = mid; }
    // El candidato de ATRÁS va primero y el desempate es estricto: cuando la
    // fecha cae justo en el medio de dos puntos conocidos, pandas se queda con
    // el anterior. Al revés daban distinto el alquiler de oct-18 y jul-19,
    // que caen a 3 días exactos de cada lado de un dato del blue.
    const cand = [];
    if (lo > 0) cand.push(serie[lo - 1]);
    cand.push(serie[lo]);
    let mejor = null, mejorD = Infinity;
    for (const c of cand) {
      const d = Math.abs(aUTC(c.fecha) - aUTC(fecha));
      if (d < mejorD) { mejorD = d; mejor = c; }
    }
    return mejor;
  }

  function ajustar(base, indice, baseF, baseV, idxF, idxV, modo) {
    const sb = aSerie(base, baseF, baseV);
    if (!sb.length) return [];
    if (modo === 'nominal' || !indice) return sb.map(p => ({ fecha: p.fecha, valor: p.valor }));
    const si = aSerie(indice, idxF, idxV);
    if (!si.length) return [];
    const out = [];
    for (const p of sb) {
      const m = asofNearest(si, p.fecha);
      if (!m || !m.valor) continue;
      out.push({ fecha: p.fecha, valor: redondear(p.valor / m.valor, 6) });
    }
    return out;
  }

  // resumen.py:41 variacion()
  function variacionDe(vIni, fIni, vFin, fFin) {
    if (!vIni) return null;
    const dias = diasEntre(fIni, fFin);
    return {
      desde: fIni, hasta: fFin,
      valor_desde: redondear(vIni, 6), valor_hasta: redondear(vFin, 6), dias,
      variacion_pct: redondear((vFin / vIni - 1) * 100, 2),
      tir_anualizada_pct: dias > 0 ? redondear(((vFin / vIni) ** (365 / dias) - 1) * 100, 2) : null,
    };
  }

  // ── Financiamiento (server.py:452) ───────────────────────────────────────
  async function financiamiento() {
    const salida = {};
    for (const familia of ['cheques', 'pagares']) {
      const tab = MULTI_TAB[familia], cols = MULTI[familia];
      const bloques = [];
      for (const [sufijo, etiquetaMoneda] of MONEDAS_CARD) {
        const tasas = [];
        for (const [seg, etiqueta] of SEGMENTOS_CARD) {
          const col = `${seg}_CORTO${sufijo}`;
          if (!cols.includes(col)) continue;
          const u = await ultimoDe(tab, col);
          tasas.push({ segmento: etiqueta, columna: col, fecha: u?.fecha ?? null, tna: u?.valor ?? null });
        }
        if (tasas.length) bloques.push({ moneda: etiquetaMoneda, sufijo, tasas });
      }
      salida[familia] = { monedas: bloques };
    }
    const plazos = [];
    for (const col of MULTI.caucion) {
      const u = await ultimoDe('CAUCION', col);
      const n = col.replace('TASA_', '').replace('D', '');
      plazos.push({ plazo: `${n} día${n === '1' ? '' : 's'}`, columna: col, fecha: u?.fecha ?? null, tna: u?.valor ?? null });
    }
    salida.caucion = { plazos };
    const tasas = [];
    for (const [familia, etiqueta] of TASAS_BCRA) {
      const u = await ultimoDe(SERIES[familia][0], SERIES[familia][1]);
      tasas.push({ familia, nombre: etiqueta, fecha: u?.fecha ?? null, tna: u?.valor ?? null });
    }
    salida.bcra = { tasas };
    return salida;
  }

  // ── REM (server.py:588-666 + api/rem_estimaciones.py) ────────────────────
  async function curvaRemActual(tipo) {
    const records = await leerRem(tipo);
    if (!records.length) return [null, []];
    const ultima = records.reduce((m, r) => (r.FECHA_PRONOSTICO > m ? r.FECHA_PRONOSTICO : m), records[0].FECHA_PRONOSTICO);
    const curva = records.filter(r => r.FECHA_PRONOSTICO === ultima)
      .sort((a, b) => a.PERIODO.localeCompare(b.PERIODO));
    return [ultima, curva];
  }

  async function curvaRemInteranual() {
    const records = await leerRem('ipc_interanual');
    if (!records.length) return [null, []];
    const ultima = records.reduce((m, r) => (r.FECHA_PRONOSTICO > m ? r.FECHA_PRONOSTICO : m), records[0].FECHA_PRONOSTICO);
    return [ultima, records.filter(r => r.FECHA_PRONOSTICO === ultima)
      .map(r => ({ PERIODO: r.PERIODO, MEDIANA: Number(r.MEDIANA) }))];
  }

  const factorCompuesto = pcts => pcts.reduce((f, p) => f * (1 + p / 100), 1);

  function ventana12Meses(periodoFin) {
    const anio = +periodoFin.slice(0, 4), mes = +periodoFin.slice(5, 7);
    const claves = [];
    for (let i = 11; i >= 0; i--) {
      const total = anio * 12 + (mes - 1) - i;
      const a = Math.floor(total / 12), m = ((total % 12) + 12) % 12 + 1;
      claves.push(`${String(a).padStart(4, '0')}-${String(m).padStart(2, '0')}`);
    }
    return claves;
  }

  function construirCurvaMensual(reales, remMensual, remInteranual) {
    const mapa = new Map();
    for (const r of reales) mapa.set(r.PERIODO.slice(0, 7), { valor_pct: redondear(Number(r.VALOR), 2), fuente: 'real' });
    for (const r of remMensual) {
      const c = r.PERIODO.slice(0, 7);
      if (!mapa.has(c)) mapa.set(c, { valor_pct: redondear(Number(r.MEDIANA), 2), fuente: 'rem_mensual' });
    }
    for (const ancla of [...remInteranual].sort((a, b) => a.PERIODO.localeCompare(b.PERIODO))) {
      const ventana = ventana12Meses(ancla.PERIODO.slice(0, 7));
      const faltantes = ventana.filter(c => !mapa.has(c));
      if (!faltantes.length) continue;
      const cubiertos = ventana.filter(c => mapa.has(c)).map(c => mapa.get(c).valor_pct);
      const factorCubierto = factorCompuesto(cubiertos);
      if (factorCubierto <= 0) continue;
      const factorObjetivo = 1 + Number(ancla.MEDIANA) / 100;
      const tasa = ((factorObjetivo / factorCubierto) ** (1 / faltantes.length) - 1) * 100;
      for (const c of faltantes) {
        mapa.set(c, { valor_pct: redondear(tasa, 2), fuente: 'rem_interanual_repartido', ancla: ancla.PERIODO.slice(0, 7) });
      }
    }
    return [...mapa.keys()].sort().map(c => ({ periodo: `${c}-01`, ...mapa.get(c) }));
  }

  function resumenPorAnio(curva, remInteranual) {
    const anualDic = {};
    for (const r of remInteranual) if (r.PERIODO.slice(5, 7) === '12') anualDic[r.PERIODO.slice(0, 4)] = Number(r.MEDIANA);
    const conteo = {};
    for (const c of curva) {
      const anio = c.periodo.slice(0, 4);
      conteo[anio] = conteo[anio] || { real: 0, rem_mensual: 0, rem_interanual_repartido: 0 };
      conteo[anio][c.fuente] = (conteo[anio][c.fuente] || 0) + 1;
    }
    const out = {};
    for (const anio of Object.keys(conteo).sort()) {
      const d = conteo[anio];
      if (!d.rem_mensual && !d.rem_interanual_repartido) continue;
      out[anio] = { rem_anual_pct: anualDic[anio] ?? null, ...d };
    }
    return out;
  }

  // ── Proyección (espejo de api/proyeccion.py) ─────────────────────────────
  // resample("ME").last(): último valor de cada mes, clave 'YYYY-MM'.
  function serieMensual(records, fechaCol, valorCol) {
    const porMes = new Map();
    for (const p of aSerieSinTope(records, fechaCol, valorCol)) porMes.set(p.fecha.slice(0, 7), p.valor);
    return porMes;   // Map preserva el orden de inserción: la serie viene ordenada
  }
  // Igual que aSerie pero sin recortar el futuro: proyeccion.py no filtra.
  function aSerieSinTope(records, fechaCol, valorCol) {
    return records
      .map(r => ({ fecha: String(r[fechaCol] || '').slice(0, 10), valor: Number(r[valorCol]) }))
      .filter(p => p.fecha && Number.isFinite(p.valor))
      .sort((a, b) => a.fecha.localeCompare(b.fecha));
  }

  function variacionesMensuales(mapaMes) {
    const claves = [...mapaMes.keys()].sort();
    const out = new Map();
    for (let i = 1; i < claves.length; i++) {
      const prev = mapaMes.get(claves[i - 1]);
      if (prev) out.set(claves[i], mapaMes.get(claves[i]) / prev - 1);
    }
    return out;
  }

  // OLS de 3 parámetros por ecuaciones normales + eliminación gaussiana.
  // np.linalg.lstsq con 3 columnas y datos bien condicionados da lo mismo.
  function ols3(filas) {
    const A = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], b = [0, 0, 0];
    for (const [x1, x2, y] of filas) {
      const x = [1, x1, x2];
      for (let i = 0; i < 3; i++) { for (let j = 0; j < 3; j++) A[i][j] += x[i] * x[j]; b[i] += x[i] * y; }
    }
    const M = A.map((fila, i) => [...fila, b[i]]);
    for (let col = 0; col < 3; col++) {
      let piv = col;
      for (let f = col + 1; f < 3; f++) if (Math.abs(M[f][col]) > Math.abs(M[piv][col])) piv = f;
      if (Math.abs(M[piv][col]) < 1e-12) return null;
      [M[col], M[piv]] = [M[piv], M[col]];
      for (let f = 0; f < 3; f++) {
        if (f === col) continue;
        const k = M[f][col] / M[col][col];
        for (let c = col; c < 4; c++) M[f][c] -= k * M[col][c];
      }
    }
    return [M[0][3] / M[0][0], M[1][3] / M[1][1], M[2][3] / M[2][2]];
  }

  function estimarModelo(objetivo, objF, objV, cer, dolar, dolarV = 'OFICIAL_VENTA') {
    const sObj = serieMensual(objetivo, objF, objV);
    const sCer = serieMensual(cer, 'FECHA', 'VALOR');
    const sFx = serieMensual(dolar, 'FECHA', dolarV);
    if (sObj.size < 6 || !sCer.size || !sFx.size) return null;

    const vObj = variacionesMensuales(sObj), vCer = variacionesMensuales(sCer), vFx = variacionesMensuales(sFx);
    const filas = [];
    for (const mes of [...vObj.keys()].sort()) {
      if (vCer.has(mes) && vFx.has(mes)) filas.push([vCer.get(mes), vFx.get(mes), vObj.get(mes)]);
    }
    if (filas.length < 6) return null;

    const coef = ols3(filas);
    if (!coef) return null;
    const [a, bIpc, bFx] = coef;
    const ys = filas.map(f => f[2]);
    const media = ys.reduce((s, v) => s + v, 0) / ys.length;
    let ssRes = 0, ssTot = 0;
    filas.forEach(([x1, x2, y]) => { const yh = a + bIpc * x1 + bFx * x2; ssRes += (y - yh) ** 2; ssTot += (y - media) ** 2; });

    const mesesObj = [...sObj.keys()].sort(), mesesFx = [...sFx.keys()].sort();
    const ultimoMes = mesesObj[mesesObj.length - 1];
    // ultima_fecha en Python es el fin de mes del resample; acá se reporta el
    // mismo mes con su último día.
    const finDeMes = m => iso(Date.UTC(+m.slice(0, 4), +m.slice(5, 7), 1) - 86400000);
    return {
      a, b_ipc: bIpc, b_fx: bFx,
      r2: redondear(ssTot > 0 ? 1 - ssRes / ssTot : 0, 4), n_obs: filas.length,
      ultimo_valor: sObj.get(ultimoMes), ultima_fecha: finDeMes(ultimoMes),
      ultimo_fx: sFx.get(mesesFx[mesesFx.length - 1]),
    };
  }

  function proyectar(modelo, remIpc, remFx) {
    if (!remIpc?.length || !remFx?.length) return [];
    const ipcPorPeriodo = new Map(remIpc.map(r => [r.PERIODO, Number(r.MEDIANA)]));
    let valor = modelo.ultimo_valor, fxAnterior = modelo.ultimo_fx;
    const out = [];
    for (const fila of [...remFx].sort((a, b) => a.PERIODO.localeCompare(b.PERIODO))) {
      const nivelFx = Number(fila.MEDIANA);
      const varIpc = ipcPorPeriodo.get(fila.PERIODO);
      if (varIpc === undefined || fxAnterior === null || fxAnterior === undefined) { fxAnterior = nivelFx; continue; }
      const varFx = nivelFx / fxAnterior - 1;
      valor *= 1 + (modelo.a + modelo.b_ipc * (varIpc / 100) + modelo.b_fx * varFx);
      out.push({ fecha: fila.PERIODO, valor: redondear(valor, 4) });
      fxAnterior = nivelFx;
    }
    return out;
  }

  // ── Router: las mismas rutas que Flask ───────────────────────────────────
  const ok = cuerpo => ({ ok: true, status: 200, json: async () => cuerpo });
  const err = (status, mensaje) => ({ ok: false, status, json: async () => ({ error: mensaje }) });

  async function get(ruta) {
    const [camino, qs] = ruta.split('?');
    const q = new URLSearchParams(qs || '');
    const partes = camino.replace(/^\/api\//, '').split('/');

    // Resumen: el snapshot que publica el job (server.py:845 publicar_resumen).
    if (camino === '/api/resumen') {
      const { filas } = await SibraSB.rest(
        'indices_resumen_publico?select=*&order=fecha_publicacion.desc&limit=1');
      if (!filas.length) return err(422, 'todavía no hay resumen publicado');
      const dia = filas[0].fecha_publicacion;
      const todas = await SibraSB.selectAll(
        `indices_resumen_publico?select=*&fecha_publicacion=eq.${dia}`);
      const porFamilia = new Map(todas.map(r => [r.familia, r]));
      return ok(RESUMEN_SERIES.map(([nombre, familia]) => {
        const r = porFamilia.get(familia) || {};
        return {
          familia, nombre,
          ultima_fecha: r.ultima_fecha ?? null, ultimo_valor: r.ultimo_valor ?? null,
          mom: r.mom ?? null, d30: r.d30 ?? null, ytd: r.ytd ?? null,
          yoy: r.yoy ?? null, yoy_anualizada: r.yoy_anualizada ?? null, a5: r.a5 ?? null,
        };
      }));
    }

    if (partes[0] === 'series') {
      const familia = decodeURIComponent(partes[1] || '');
      if (familia === 'dolar') return ok(await leer(DOLAR_TAB));
      if (familia === 'caucion') return ok(await leer('CAUCION'));
      if (familia === 'cheques') return ok(await leer('CHEQUES'));
      if (familia === 'pagares') return ok(await leer('PAGARES'));
      if (!SERIES[familia]) return err(404, `familia desconocida: ${familia}`);
      return ok(await leer(SERIES[familia][0]));
    }

    if (camino === '/api/financiamiento') return ok(await financiamiento());

    if (camino === '/api/ajustar') {
      const familia = q.get('familia') || '', indice = q.get('indice') || 'ninguno';
      const base = await resolverFamilia(familia, q.get('item'));
      if (!base) return err(404, `familia desconocida: ${familia}`);
      if (indice === 'ninguno') {
        return ok(ajustar(base.records, null, base.fechaCol, base.valorCol, null, null, 'nominal'));
      }
      const idx = await serieIndice(indice);
      if (!idx) return err(404, `índice desconocido: ${indice}`);
      return ok(ajustar(base.records, idx.records, base.fechaCol, base.valorCol, idx.fechaCol, idx.valorCol, 'ratio'));
    }

    if (camino === '/api/variacion') {
      const familia = q.get('familia'), desde = q.get('desde'), hasta = q.get('hasta');
      const indice = q.get('indice');
      if (!familia || !desde || !hasta) return err(400, 'faltan parámetros: familia, desde, hasta');

      // Atajo: sin índice y con familia que sale de una columna, dos consultas
      // de una fila cada una — no hace falta bajarse la serie entera.
      const donde = (!indice || indice === 'ninguno') ? ubicarFamilia(familia) : null;
      if (donde) {
        const tope = hoyISO();
        const [ini, fin] = await Promise.all([
          ultimoDe(donde.tab, donde.columna, desde < tope ? desde : tope),
          ultimoDe(donde.tab, donde.columna, hasta < tope ? hasta : tope),
        ]);
        if (!ini || !fin) return err(422, 'no hay datos suficientes en ese rango');
        const r = variacionDe(ini.valor, ini.fecha, fin.valor, fin.fecha);
        return r ? ok(r) : err(422, 'no hay datos suficientes en ese rango');
      }

      const base = await resolverFamilia(familia, q.get('item'));
      if (!base) return err(404, `familia desconocida: ${familia}`);
      let serie = aSerie(base.records, base.fechaCol, base.valorCol);
      if (indice && indice !== 'ninguno') {
        const idx = await serieIndice(indice);
        if (!idx) return err(404, `índice desconocido: ${indice}`);
        serie = ajustar(base.records, idx.records, base.fechaCol, base.valorCol, idx.fechaCol, idx.valorCol, 'ratio')
          .map(p => ({ fecha: p.fecha, valor: p.valor }));
      }
      const ini = enOAntes(serie, desde), fin = enOAntes(serie, hasta);
      if (!ini || !fin) return err(422, 'no hay datos suficientes en ese rango');
      const r = variacionDe(ini.valor, ini.fecha, fin.valor, fin.fecha);
      return r ? ok(r) : err(422, 'no hay datos suficientes en ese rango');
    }

    if (partes[0] === 'rem') {
      const tipo = partes[1];
      if (tipo === 'anual') {
        const [relevamiento, curva] = await curvaRemInteranual();
        const anuales = curva.filter(c => c.PERIODO.slice(5, 7) === '12')
          .map(c => ({ anio: +c.PERIODO.slice(0, 4), mediana: c.MEDIANA }))
          .sort((a, b) => a.anio - b.anio);
        return ok({ relevamiento, curva: anuales });
      }
      if (tipo === 'estimaciones') {
        const [relevamientoAnual, curvaInteranual] = await curvaRemInteranual();
        if (!curvaInteranual.length) return err(422, 'no hay REM interanual cargado todavía');
        const [, curvaMensualRem] = await curvaRemActual('ipc');
        const reales = (await leer('INFLACION_INDEC')).map(r => ({ PERIODO: r.FECHA, VALOR: r.VALOR }));
        const remMensual = curvaMensualRem.map(r => ({ PERIODO: r.PERIODO, MEDIANA: r.MEDIANA }));
        const curva = construirCurvaMensual(reales, remMensual, curvaInteranual);
        return ok({ relevamiento_anual: relevamientoAnual, curva, resumen_anual: resumenPorAnio(curva, curvaInteranual) });
      }
      if (tipo !== 'ipc' && tipo !== 'fx') return err(404, `tipo desconocido: ${tipo}`);
      const [relevamiento, curva] = await curvaRemActual(tipo);
      return ok({ relevamiento, curva });
    }

    if (camino === '/api/proyectar') {
      const familia = q.get('familia');
      if (!PROYECTABLES.has(familia)) return err(404, `familia no proyectable: ${familia}`);
      const [tab, col] = SERIES[familia];
      const [objetivo, cer, dolar] = await Promise.all([leer(tab), leer('CER'), leer(DOLAR_TAB)]);
      const modelo = estimarModelo(objetivo, 'FECHA', col, cer, dolar);
      if (!modelo) return err(422, 'no hay suficiente historia en común (mínimo 6 meses)');
      const [, curvaIpc] = await curvaRemActual('ipc');
      const [, curvaFx] = await curvaRemActual('fx');
      return ok({ modelo, proyeccion: proyectar(modelo, curvaIpc, curvaFx) });
    }

    if (partes[0] === 'materiales') {
      if (partes[1] === 'proveedores') return ok(await proveedoresMateriales());
      const idProv = decodeURIComponent(partes[1] || '');
      const proveedores = await proveedoresMateriales();
      if (!(idProv in proveedores)) return err(404, 'proveedor no reconocido o sin precios cargados');
      const registros = await cotizacionesMaterial(idProv);
      if (partes[2] !== 'items') return ok(registros);
      const conteo = new Map();
      for (const r of registros) {
        if (!r.DESCRIPCION) continue;
        conteo.set(r.DESCRIPCION, (conteo.get(r.DESCRIPCION) || 0) + 1);
      }
      const curados = MATERIALES_CURADOS[idProv];
      return ok(curados
        ? curados.map(d => ({ descripcion: d, cotizaciones: conteo.get(d) || 0 }))
        : [...conteo.keys()].sort().map(d => ({ descripcion: d, cotizaciones: conteo.get(d) })));
    }

    // /api/estado-sync y /api/uso-supabase son cosas del server local: no
    // existen acá y la página ya los trata como opcionales.
    return err(404, `sin ruta: ${camino}`);
  }

  return { get, leer, leerRem, resolverFamilia, ajustar, aSerie, enOAntes, variacionDe, construirIndiceNivel,
           construirCurvaMensual, resumenPorAnio, estimarModelo, proyectar, financiamiento };
})();

// ═══════════════════════════════════════════════════════════════════════════
//  sibra-sb.js — Índices leyendo Supabase directo, sin api/server.py.
//
//  POR QUÉ EXISTE: index.html se publica en GitHub Pages (sibraweb.github.io/
//  data/), que es estático — ahí no corre Flask, y las 15 llamadas a
//  `${API}/api/...` daban 404. La página quedaba con el cartel rojo "¿Está
//  corriendo api/server.py?" desde siempre: nunca tuvo backend.
//
//  QUÉ HACE: implementa las MISMAS rutas `/api/...` contra Supabase, con la
//  misma forma de respuesta. El resto de index.html no se entera de dónde
//  salieron los datos — solo cambia quién contesta:
//      - con api/server.py escuchando (local, 8100)  -> contesta Flask
//      - sin él (Pages)                               -> contesta este módulo
//
//  LOGIN: las tablas son de lectura `authenticated` — la publishable key sola
//  no lee nada. Es el mismo Supabase Auth de Market Suite y comparte la MISMA
//  clave de sesión en localStorage: como /market/ y /data/ son el mismo
//  origen, quien ya entró en Market Suite entra acá sin volver a loguearse.
//
//  Andan las once pestañas. Materiales era la excepción —sus precios salían de
//  la Sheet del Drive de Obra, por OAuth de Google— hasta que el 06/09 se
//  unificó todo en la tabla `cotizaciones`: ahora también sale de la base.
// ═══════════════════════════════════════════════════════════════════════════
const SibraSB = (() => {
  const SUPABASE_URL = 'https://mkbeddulfbqgyutrzyvr.supabase.co';
  // Publishable key (dashboard -> Settings -> API Keys). Es segura de exponer:
  // sin sesión, RLS no devuelve una sola fila.
  const ANON_KEY = 'sb_publishable_ewknnbpVirEVndioUqqDrw_5_N5oyZf';
  // MISMA clave que markets-repo/shared/sibra-maestros.js — un login para los dos.
  const SESSION_KEY = 'sibra_sb_session';

  // ── Sesión ───────────────────────────────────────────────────────────────
  const loadSession = () => { try { return JSON.parse(localStorage.getItem(SESSION_KEY)) || null; } catch { return null; } };
  const saveSession = s => s ? localStorage.setItem(SESSION_KEY, JSON.stringify(s)) : localStorage.removeItem(SESSION_KEY);
  const sessionEmail = () => loadSession()?.email || null;

  async function authFetch(path, body) {
    const r = await fetch(`${SUPABASE_URL}/auth/v1/${path}`, {
      method: 'POST',
      headers: { apikey: ANON_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error_description || data.msg || data.message || `Auth ${r.status}`);
    return data;
  }

  function guardarDeToken(d, emailFallback) {
    saveSession({
      access_token: d.access_token, refresh_token: d.refresh_token,
      expires_at: Date.now() + (d.expires_in - 60) * 1000,
      email: d.user?.email || emailFallback,
    });
  }

  async function login(email, password) {
    guardarDeToken(await authFetch('token?grant_type=password', { email, password }), email);
  }

  async function refresh() {
    const s = loadSession();
    if (!s?.refresh_token) return null;
    try {
      guardarDeToken(await authFetch('token?grant_type=refresh_token', { refresh_token: s.refresh_token }), s.email);
      return loadSession();
    } catch { saveSession(null); return null; }
  }

  function logout() { saveSession(null); }

  async function getToken() {
    let s = loadSession();
    if (!s) return null;
    if (Date.now() >= s.expires_at) s = await refresh();
    return s?.access_token || null;
  }

  // ── Modal de login ───────────────────────────────────────────────────────
  let modalPromise = null;
  function ensureLogin() {
    return getToken().then(tok => {
      if (tok) return tok;
      if (modalPromise) return modalPromise;
      modalPromise = new Promise(resolve => {
        const wrap = document.createElement('div');
        wrap.innerHTML = [
          '<div style="position:fixed;inset:0;background:rgba(15,20,20,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif">',
          '  <div style="background:#fff;border:1px solid #e3e6e6;border-radius:12px;padding:28px;width:340px;box-shadow:0 18px 48px rgba(0,0,0,.25)">',
          '    <div style="font-size:14px;font-weight:800;letter-spacing:.4px;margin-bottom:4px">SIBRA · Índices</div>',
          '    <div style="font-size:11.5px;color:#5A6060;margin-bottom:16px;line-height:1.45">Los índices viven en la base (Supabase) y se leen con tu usuario. Es el mismo de Market Suite.</div>',
          '    <input id="sbEmail" type="email" placeholder="email" autocomplete="username" style="width:100%;box-sizing:border-box;margin-bottom:8px;padding:9px 10px;border:1px solid #d6dada;border-radius:7px;font-size:13px">',
          '    <input id="sbPass" type="password" placeholder="contraseña" autocomplete="current-password" style="width:100%;box-sizing:border-box;margin-bottom:12px;padding:9px 10px;border:1px solid #d6dada;border-radius:7px;font-size:13px">',
          '    <div id="sbErr" style="color:#DC2626;font-size:11.5px;min-height:16px;margin-bottom:8px"></div>',
          '    <button id="sbGo" style="width:100%;padding:10px;border:0;border-radius:7px;background:#111;color:#fff;font-size:13px;font-weight:700;cursor:pointer">Entrar</button>',
          '  </div>',
          '</div>',
        ].join('\n');
        document.body.appendChild(wrap);
        const $ = id => wrap.querySelector('#' + id);
        const entrar = async () => {
          $('sbErr').textContent = '';
          $('sbGo').disabled = true;
          try {
            await login($('sbEmail').value.trim(), $('sbPass').value);
            wrap.remove();
            modalPromise = null;
            resolve(await getToken());
          } catch (e) {
            $('sbErr').textContent = e.message || 'No se pudo entrar';
            $('sbGo').disabled = false;
          }
        };
        $('sbGo').addEventListener('click', entrar);
        // El Enter va atado a CADA campo, no al contenedor: apoyado en el div
        // de afuera no llegaba a dispararse y había que ir al botón con el
        // mouse. Es el mismo enganche que usa el modal de Market Suite.
        [$('sbEmail'), $('sbPass')].forEach(el =>
          el.addEventListener('keydown', e => { if (e.key === 'Enter') entrar(); }));
        $('sbEmail').focus();
      });
      return modalPromise;
    });
  }

  // ── PostgREST ────────────────────────────────────────────────────────────
  const PAGINA = 1000;   // db-max-rows del proyecto: nunca devuelve más de 1000

  async function rest(pathQuery, rango) {
    const tok = await ensureLogin();
    const headers = { apikey: ANON_KEY, Authorization: 'Bearer ' + tok };
    if (rango) { headers.Range = rango; headers['Range-Unit'] = 'items'; headers.Prefer = 'count=exact'; }
    const r = await fetch(`${SUPABASE_URL}/rest/v1/${pathQuery}`, { headers });
    if (!r.ok) throw new Error(`Supabase ${r.status}: ${await r.text()}`);
    const total = Number((r.headers.get('content-range') || '').split('/')[1]);
    return { filas: await r.json(), total: Number.isFinite(total) ? total : null };
  }

  // Trae una tabla completa. La primera página dice cuántas filas hay en total
  // (Prefer: count=exact) y las que faltan se piden EN PARALELO — DOLAR son
  // 25.000 filas = 26 páginas, y en serie eso es medio minuto de espera.
  async function selectAll(pathQuery) {
    const primera = await rest(pathQuery, `0-${PAGINA - 1}`);
    if (primera.total === null || primera.total <= PAGINA) return primera.filas;
    const pedidos = [];
    for (let desde = PAGINA; desde < primera.total; desde += PAGINA) {
      pedidos.push(rest(pathQuery, `${desde}-${desde + PAGINA - 1}`).then(p => p.filas));
    }
    const resto = await Promise.all(pedidos);
    return primera.filas.concat(...resto);
  }

  return { SUPABASE_URL, ANON_KEY, login, logout, ensureLogin, getToken, sessionEmail, rest, selectAll };
})();

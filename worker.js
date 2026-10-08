const json = (data, status = 200, extra = {}) => new Response(JSON.stringify(data), {
  status,
  headers: { 'content-type': 'application/json; charset=utf-8', ...extra }
});

const prices = {
  'Haircut & Styling — $10': '$10',
  'Beard Trimming & Grooming — $7': '$7',
  'Hair Treatment — $5': '$5',
  'Special Service — Doorstep': 'Contact for price'
};

function b64url(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
function fromB64url(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s); return Uint8Array.from(bin, c => c.charCodeAt(0));
}
async function hmac(secret, text) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(text)));
}
async function makeToken(secret) {
  const payload = b64url(new TextEncoder().encode(JSON.stringify({ exp: Date.now() + 12 * 60 * 60 * 1000 })));
  return payload + '.' + b64url(await hmac(secret, payload));
}
async function validToken(secret, token) {
  if (!token || !token.includes('.')) return false;
  const [payload, sig] = token.split('.');
  try {
    const data = JSON.parse(new TextDecoder().decode(fromB64url(payload)));
    if (!data.exp || Date.now() > data.exp) return false;
    const expected = await hmac(secret, payload);
    const actual = fromB64url(sig);
    if (actual.length !== expected.length) return false;
    let diff = 0; for (let i=0;i<expected.length;i++) diff |= expected[i] ^ actual[i];
    return diff === 0;
  } catch { return false; }
}
function adminToken(request) {
  return request.headers.get('X-Admin-Token') || (request.headers.get('Cookie') || '').match(/royalty_admin=([^;]+)/)?.[1] || '';
}

async function api(request, env) {
  if (!env.DB) return json({error:'Database is not connected yet.'}, 503);
  const url = new URL(request.url);
  const path = url.pathname;

  if (request.method === 'POST' && path === '/api/bookings') {
    let d; try { d = await request.json(); } catch { return json({error:'Invalid request.'},400); }
    const required = ['name','phone','service','date','time','location'];
    if (required.some(k => !String(d[k] ?? '').trim())) return json({error:'Missing required booking details.'},400);
    const existing = await env.DB.prepare("SELECT id FROM bookings WHERE date=? AND time=? AND appointment_status NOT IN ('cancelled','completed') LIMIT 1").bind(d.date,d.time).first();
    if (existing) return json({error:'That time is already booked. Please choose another time.'},409);
    const result = await env.DB.prepare(`INSERT INTO bookings (name,phone,service,date,time,location,note,price,created_at) VALUES (?,?,?,?,?,?,?,?,?)`)
      .bind(d.name,d.phone,d.service,d.date,d.time,d.location,d.note || '',prices[d.service] || 'Contact for price',new Date().toISOString()).run();
    return json({id: result.meta.last_row_id, status:'pending'},201);
  }

  if (request.method === 'GET' && path === '/api/availability') {
    const date = url.searchParams.get('date') || '';
    const rows = await env.DB.prepare("SELECT time FROM bookings WHERE date=? AND appointment_status NOT IN ('cancelled','completed') ORDER BY time").bind(date).all();
    return json({booked:(rows.results || []).map(r=>r.time)});
  }

  if (request.method === 'POST' && path === '/api/admin/login') {
    let d; try { d = await request.json(); } catch { return json({error:'Invalid request.'},400); }
    if (!env.ADMIN_PASSWORD || String(d.password || '') !== env.ADMIN_PASSWORD) return json({error:'Invalid password'},401);
    const token = await makeToken(env.ADMIN_SECRET || env.ADMIN_PASSWORD);
    return json({token},200,{'set-cookie':`royalty_admin=${token}; Path=/; Max-Age=43200; HttpOnly; Secure; SameSite=Lax`});
  }

  const token = adminToken(request);
  if (path.startsWith('/api/admin/') && !(await validToken(env.ADMIN_SECRET || env.ADMIN_PASSWORD, token))) return json({error:'Unauthorized'},401);

  if (request.method === 'POST' && path === '/api/admin/logout') return json({ok:true},200,{'set-cookie':'royalty_admin=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax'});

  if (request.method === 'GET' && path === '/api/admin/bookings') {
    const rows = await env.DB.prepare('SELECT * FROM bookings ORDER BY date,time,id').all();
    return json({bookings:rows.results || []});
  }

  if (request.method === 'PATCH' && path.startsWith('/api/admin/bookings/')) {
    const id = path.split('/').pop(); let d; try { d = await request.json(); } catch { return json({error:'Invalid request.'},400); }
    const allowed = ['payment_status','appointment_status'];
    const updates = allowed.filter(k => d[k] !== undefined);
    if (!updates.length) return json({error:'No valid changes'},400);
    const vals = updates.map(k=>d[k]);
    const sql = `UPDATE bookings SET ${updates.map(k=>k+'=?').join(',')} WHERE id=?`;
    await env.DB.prepare(sql).bind(...vals,id).run();
    return json({ok:true});
  }
  return json({error:'Not found'},404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) return api(request, env);
    return env.ASSETS.fetch(request);
  }
};

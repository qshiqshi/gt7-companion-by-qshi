/* Small helpers for the plain pages. */
export async function get(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw Object.assign(new Error(path), { status: response.status });
  return response.json();
}

export async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await response.json(); } catch (e) { /* no body */ }
  if (!response.ok) throw Object.assign(new Error(path), { status: response.status, detail: data && data.detail });
  return data;
}

export const byId = id => document.getElementById(id);

/* Only addresses inside this site are followed after pairing. */
export function safeNext(fallback) {
  const next = new URLSearchParams(location.search).get('next') || '';
  return /^\/(?!\/)/.test(next) ? next : fallback;
}

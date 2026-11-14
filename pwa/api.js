// tacit: the API wrapper. Same origin only, cookies "same-origin", JSON in and out.
// Errors become short messages the screens can show as they are.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const FALLBACK = {
  400: "That didn't look right. Check it and try again.",
  401: 'Please start again: you are not signed in.',
  403: "That isn't allowed right now.",
  404: "That isn't there any more.",
  409: 'That already exists.',
  413: 'That is too big.',
  422: "Something in the form isn't valid.",
  429: "That's enough for today. Try again tomorrow.",
  502: "Something on our side didn't answer. Try again in a minute.",
  503: "That isn't set up yet.",
};

function messageFor(status, data) {
  const d = data && data.detail;
  if (typeof d === 'string' && d) return d.charAt(0).toUpperCase() + d.slice(1);
  if (Array.isArray(d) && d.length && d[0] && d[0].msg) return "Something in the form isn't valid.";
  return FALLBACK[status] || 'Something went wrong. Try again.';
}

export async function api(path, { method = 'GET', body } = {}) {
  if (typeof path !== 'string' || !path.startsWith('/')) throw new ApiError(0, 'bad path');
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(path, init);
  } catch {
    throw new ApiError(0, "You're offline. Try again when you're back online.");
  }
  if (r.status === 204) return null;
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) throw new ApiError(r.status, messageFor(r.status, data));
  return data;
}

export const get = (path) => api(path);
export const post = (path, body) => api(path, { method: 'POST', body: body ?? {} });
export const patch = (path, body) => api(path, { method: 'PATCH', body });
export const del = (path) => api(path, { method: 'DELETE' });

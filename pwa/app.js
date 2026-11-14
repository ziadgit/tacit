// tacit PWA: the hash router and the screens. Every piece of API data goes into the page with
// textContent or attributes, never as markup.
import { ApiError, del, get, patch, post } from './api.js';

const E164 = /^\+[1-9]\d{7,14}$/;
const TAGLINE = 'agents have skills. people have taste. tacit is how it gets around.';
const LAST_ROUTE = 'tacit:last-route'; // the only thing kept in localStorage
const PUBLIC_ROUTES = new Set(['start']);

const state = { me: null, config: null, timers: [], route: null };

// ---- tiny DOM helpers ------------------------------------------------------------------

export function h(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k === 'checked' || k === 'disabled' || k === 'hidden' || k === 'value') n[k] = v;
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const $ = (sel, root = document) => root.querySelector(sel);

function title(text) {
  return h('h1', { class: 'tc-title screen-title', text });
}

function phrase(text) {
  return h('h2', { class: 'tc-phrase', text });
}

function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4000);
}

function errorText(e) {
  return e instanceof ApiError ? e.message : 'Something went wrong. Try again.';
}

// Run an action from a button: disable it while it runs and show any error.
async function act(btn, fn) {
  if (btn) btn.disabled = true;
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { state.me = null; go('#/start'); }
    toast(errorText(e));
    return undefined;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function every(ms, fn) {
  const id = setInterval(fn, ms);
  state.timers.push(id);
  return id;
}

function clearTimers() {
  for (const id of state.timers) clearInterval(id);
  state.timers = [];
}

export function domainOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

export function firstName(name) {
  return String(name || '').trim().split(/\s+/)[0] || '';
}

// A two-step "are you sure" inside the page, never a browser dialog.
function twoStep(label, sure, onYes, cls = 'tc-btn quiet') {
  const wrap = h('div', { class: 'two-step' });
  const first = h('button', { type: 'button', class: cls, text: label });
  first.addEventListener('click', () => {
    wrap.replaceChildren(
      h('span', { class: 'ask', text: sure }),
      h('button', { type: 'button', class: 'tc-btn', text: 'yes', onclick: (ev) => onYes(ev.currentTarget) }),
      h('button', { type: 'button', class: 'tc-btn quiet', text: 'no', onclick: () => wrap.replaceChildren(first) }),
    );
  });
  wrap.append(first);
  return wrap;
}

async function refreshMe() {
  try {
    state.me = await get('/api/me');
  } catch (e) {
    state.me = null;
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
  }
  return state.me;
}

// ---- screens ---------------------------------------------------------------------------

const screens = {};

screens.start = function start(root) {
  const links = h('div', { class: 'links' });
  const addLink = () => {
    if (links.children.length >= 5) return;
    links.append(h('input', { type: 'url', name: 'link', inputmode: 'url', autocomplete: 'url',
      placeholder: 'https://', 'aria-label': `link ${links.children.length + 1}` }));
    more.hidden = links.children.length >= 5;
  };
  const more = h('button', { type: 'button', class: 'tc-textlink', text: 'add another link', onclick: addLink });
  addLink();
  const err = h('p', { class: 'form-error', role: 'alert', hidden: true });
  const form = h('form', { class: 'tc-card form', novalidate: true },
    h('label', {}, h('span', { text: 'your name' }),
      h('input', { name: 'name', required: true, maxlength: 80, autocomplete: 'name' })),
    h('label', {}, h('span', { text: 'your phone, with the country code' }),
      h('input', { name: 'phone', type: 'tel', required: true, autocomplete: 'tel', placeholder: '+1 415 555 0100' })),
    h('label', {}, h('span', { text: 'a line about you (optional)' }),
      h('input', { name: 'headline', maxlength: 140, placeholder: 'Ten years in product' })),
    h('fieldset', {}, h('legend', { text: 'links about you (up to 5, optional)' }), links, more),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'consent_lookup' }),
      h('span', { text: "Look me up on the web (Exa) so the interview starts from what's public" })),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'consent_call' }),
      h('span', { text: 'tacit may call me at this number' })),
    h('p', { class: 'note', text: "Calls are recorded only as the skills you approve. We don't keep the audio or the transcript." }),
    err,
    h('button', { type: 'submit', class: 'tc-btn wide', text: 'start' }),
  );
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    const f = new FormData(form);
    const phone = normalisePhone(f.get('phone'));
    const name = String(f.get('name') || '').trim();
    const linkList = f.getAll('link').map((l) => String(l).trim()).filter(Boolean);
    const problem = !name ? 'Please give your name.'
      : !E164.test(phone) ? 'Please give your number with the country code, like +1 415 555 0100.'
      : linkList.some((l) => !/^https?:\/\/\S+\.\S+/.test(l)) ? 'Links need to start with https://'
      : null;
    if (problem) { err.textContent = problem; err.hidden = false; return; }
    const body = { name, phone, links: linkList,
      headline: String(f.get('headline') || '').trim() || null,
      consent_lookup: f.get('consent_lookup') === 'on', consent_call: f.get('consent_call') === 'on' };
    await act(form.querySelector('button[type=submit]'), async () => {
      state.me = await post('/api/onboarding', body);
      go(state.me.consent_lookup ? '#/context' : '#/call');
    });
  });
  root.replaceChildren(
    h('div', { class: 'hero' },
      h('p', { class: 'tc-word big' }, 'tac', h('span', { class: 'bi', text: 'i' }), 't'),
      h('p', { class: 'tc-line', text: TAGLINE })),
    phrase('connect your context'),
    form,
  );
};

export function normalisePhone(raw) {
  const s = String(raw || '').replace(/[\s().-]/g, '');
  return s.startsWith('00') ? `+${s.slice(2)}` : s;
}

screens.context = function context(root) {
  const me = state.me;
  const list = h('div', { class: 'stack' });
  const draw = () => {
    const items = state.me.context || [];
    list.replaceChildren(...(items.length ? items.map(contextCard)
      : [h('p', { class: 'muted', text: 'Nothing found yet. That is a fine result: the interview starts from what you say.' })]));
  };
  const canLook = me.consent_lookup && state.config.lookup_enabled;
  const look = h('button', { type: 'button', class: 'tc-btn on-ground', text: 'look me up', hidden: !canLook });
  look.addEventListener('click', () => act(look, async () => {
    const found = await post('/api/context/lookup');
    await refreshMe();
    draw();
    toast(found.length ? `Found ${found.length}. Keep only what is right.` : 'Nothing found. That is fine.');
  }));
  draw();
  root.replaceChildren(
    title('your context'),
    h('p', { class: 'lede', text: me.consent_lookup
      ? 'Exa looks you up from what you gave us. Keep what is right about you; only kept items go into the interview.'
      : 'You chose not to be looked up. You can turn it on in "me".' }),
    look,
    list,
    h('a', { class: 'tc-btn on-ground quiet wide', href: '#/call', text: 'next: a short conversation' }),
  );
};

function contextCard(item) {
  const card = h('article', { class: `tc-card ctx ${item.status}` },
    h('p', { class: 'kind', text: item.kind }),
    h('p', { class: 'ctx-text', text: item.text }),
    h('p', { class: 'src', text: domainOf(item.source_url) || 'source' }));
  const row = h('div', { class: 'row' });
  const set = (status) => (ev) => act(ev.currentTarget, async () => {
    const out = await patch(`/api/context/${encodeURIComponent(item.id)}`, { status });
    Object.assign(item, out);
    card.replaceWith(contextCard(item));
  });
  row.append(
    h('button', { type: 'button', class: item.status === 'kept' ? 'tc-btn' : 'tc-btn quiet', text: 'keep', 'aria-pressed': String(item.status === 'kept'), onclick: set('kept') }),
    h('button', { type: 'button', class: item.status === 'removed' ? 'tc-btn' : 'tc-btn quiet', text: 'remove', 'aria-pressed': String(item.status === 'removed'), onclick: set('removed') }));
  card.append(row);
  return card;
}

const CALL_WORDS = { queued: 'calling you soon', ringing: 'ringing', 'in-progress': 'in the call',
  ended: 'ended', failed: "the call didn't start" };

screens.call = function call(root) {
  const cfg = state.config;
  const status = h('p', { class: 'call-status', 'aria-live': 'polite' });
  const live = h('div', { class: 'stack' });
  const btn = h('button', { type: 'button', class: 'tc-btn on-ground wide', text: 'call me',
    hidden: !(cfg.calls_enabled && state.me.consent_call) });
  const inbound = cfg.phone_display
    ? h('p', { class: 'lede' }, 'or call ', h('a', { class: 'tel', href: `tel:${cfg.phone_display.replace(/[^\d+]/g, '')}`, text: cfg.phone_display }), ' from the number you gave us')
    : null;
  let since = null;
  let polling = null;
  const tick = async () => {
    let s;
    try { s = await get('/api/call/status'); } catch (e) { status.textContent = errorText(e); return; }
    if (!s.call) { status.textContent = 'no call yet'; return; }
    since = since || s.call.created_at;
    status.textContent = `${CALL_WORDS[s.call.status] || s.call.status}${s.skills ? ` · ${s.skills} saved` : ''}`;
    btn.hidden = s.active || !(cfg.calls_enabled && state.me.consent_call);
    const mine = await get('/api/skills/mine').catch(() => []);
    const fresh = mine.filter((k) => k.source === 'interview' && k.created_at >= since);
    live.replaceChildren(...fresh.map((k) => h('article', { class: 'tc-card saved' },
      h('h3', { class: 'card-title', text: k.title }), h('p', { text: k.verdict || '' }))));
    if (!s.active && polling) { clearInterval(polling); polling = null; }
    if (s.active && !polling) polling = every(3000, tick);
  };
  btn.addEventListener('click', () => act(btn, async () => {
    const c = await post('/api/call');
    since = c.created_at;
    status.textContent = CALL_WORDS[c.status] || c.status;
    if (!polling) polling = every(3000, tick);
  }));
  root.replaceChildren(
    title('a short conversation'),
    h('p', { class: 'lede', text: 'tacit calls you and asks about something you know how to do but never wrote down. Each skill it hears is saved as a draft for you to check.' }),
    btn,
    inbound,
    state.me.consent_call ? null : h('p', { class: 'muted', text: 'Turn on "tacit may call me" in "me" to get a call.' }),
    status,
    live,
    h('a', { class: 'tc-btn on-ground quiet wide', href: '#/skills', text: 'see my skills' }),
  );
  tick();
};

export function jevLine(score) {
  if (score === null || score === undefined) return null;
  return score >= 0.5 ? 'looks specific' : 'might be generic';
}

screens.skills = async function skills(root) {
  root.replaceChildren(title('your skills'), h('p', { class: 'muted', text: 'loading…' }));
  const mine = await get('/api/skills/mine');
  const list = h('div', { class: 'stack' });
  list.replaceChildren(...(mine.length ? mine.map(ownSkillCard)
    : [h('p', { class: 'lede', text: 'No skills yet. Have a short conversation with tacit and they will appear here.' }),
      h('a', { class: 'tc-btn on-ground wide', href: '#/call', text: 'have a conversation' })]));
  root.replaceChildren(title('your skills'),
    h('p', { class: 'lede', text: 'Drafts are only yours. Publish the ones that are right.' }), list);
};

export function skillBody(s, signer) {
  const kids = [
    h('div', { class: 'top' },
      h('span', { class: 'tag-phrase', text: s.status === 'published' ? (s.visibility === 'followers' ? 'for followers' : 'public') : s.status }),
      signer ? h('span', { class: 'sig' }, h('small', { text: 'from' }), signer) : null),
    h('h3', { class: 'card-title', text: s.title }),
  ];
  if (s.locked) {
    kids.push(h('p', { class: 'muted-ink', text: 'for followers who unlocked this person\'s skills' }));
    return kids;
  }
  kids.push(h('p', { class: 'verdict', text: s.verdict || '' }));
  if (s.reason) kids.push(h('p', { class: 'reason' }, h('em', { text: 'why: ' }), s.reason));
  if (s.quote) kids.push(h('p', { class: 'tc-said quote', text: `“${s.quote}”` }));
  return kids;
}

function ownSkillCard(s) {
  const card = h('article', { class: 'tc-card skill' });
  const draw = () => {
    const jev = jevLine(s.jev_specific);
    const acts = h('div', { class: 'acts' });
    const update = (fields) => (ev) => act(ev.currentTarget, async () => {
      Object.assign(s, await patch(`/api/skills/${encodeURIComponent(s.id)}`, fields));
      draw();
    });
    if (s.status !== 'published') acts.append(h('button', { type: 'button', class: 'tc-btn', text: 'publish', onclick: update({ status: 'published' }) }));
    acts.append(
      h('button', { type: 'button', class: 'tc-btn quiet', text: s.visibility === 'public' ? 'make it followers-only' : 'make it public',
        onclick: update({ visibility: s.visibility === 'public' ? 'followers' : 'public' }) }),
      h('button', { type: 'button', class: 'tc-textlink', text: 'edit', onclick: () => card.replaceChildren(editForm(s, draw)) }),
      twoStep('remove', 'remove it everywhere?', (b) => act(b, async () => {
        await patch(`/api/skills/${encodeURIComponent(s.id)}`, { status: 'removed' });
        card.remove();
      }), 'tc-textlink'));
    card.replaceChildren(...skillBody(s), jev ? h('p', { class: 'jev', text: jev }) : null, acts);
  };
  draw();
  return card;
}

function editForm(s, done) {
  const field = (name, label, max, value, area = true) => h('label', {}, h('span', { text: label }),
    h(area ? 'textarea' : 'input', { name, maxlength: max, value: value || '', rows: area ? 3 : null }));
  const form = h('form', { class: 'form' },
    field('title', 'title', 80, s.title, false),
    field('verdict', 'what to do', 280, s.verdict),
    field('reason', 'why', 280, s.reason),
    field('quote', 'their own words', 200, s.quote),
    h('div', { class: 'acts' },
      h('button', { type: 'submit', class: 'tc-btn', text: 'save' }),
      h('button', { type: 'button', class: 'tc-textlink', text: 'cancel', onclick: done })));
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const body = {};
    for (const k of ['title', 'verdict', 'reason', 'quote']) body[k] = String(f.get(k) || '').trim();
    if (!body.title || !body.verdict || !body.reason) { toast('A skill needs a title, what to do and why.'); return; }
    act(form.querySelector('[type=submit]'), async () => {
      Object.assign(s, await patch(`/api/skills/${encodeURIComponent(s.id)}`, body));
      done();
    });
  });
  return form;
}

// Sections other modules of the "me" screen can add (the band, the picture).
export const meSections = [];

screens.me = function me(root) {
  const m = state.me;
  const toggle = (name, label) => {
    const box = h('input', { type: 'checkbox', checked: Boolean(m[name]) });
    box.addEventListener('change', () => act(box, async () => {
      state.me = await patch('/api/me', { [name]: box.checked });
    }).then(() => { box.checked = Boolean(state.me && state.me[name]); }));
    return h('label', { class: 'check' }, box, h('span', { text: label }));
  };
  root.replaceChildren(
    title(firstName(m.name).toLowerCase() || 'me'),
    m.headline ? h('p', { class: 'lede', text: m.headline }) : null,
    h('p', { class: 'counts', text: `${m.counts.published} published · ${m.counts.followers} followers · ${m.counts.following} following` }),
    phrase('what you agreed to'),
    h('div', { class: 'tc-card form' },
      toggle('consent_lookup', "Look me up on the web (Exa) so the interview starts from what's public"),
      toggle('consent_call', 'tacit may call me at this number')),
    ...meSections.map((section) => section(state)),
    phrase('leave'),
    h('div', { class: 'tc-card form' },
      h('button', { type: 'button', class: 'tc-btn quiet', text: 'sign out', onclick: (ev) => act(ev.currentTarget, async () => {
        await post('/api/signout');
        state.me = null;
        go('#/start');
      }) }),
      twoStep('delete everything', 'This deletes your account, skills, follows and calls. Delete everything?', (b) => {
        b.closest('.two-step').replaceChildren(
          h('span', { class: 'ask', text: 'Really? This cannot be undone.' }),
          h('button', { type: 'button', class: 'tc-btn', text: 'yes, delete everything', onclick: (ev) => act(ev.currentTarget, async () => {
            await del('/api/me');
            state.me = null;
            toast('Everything is deleted.');
            go('#/start');
          }) }),
          h('button', { type: 'button', class: 'tc-btn quiet', text: 'keep my account', onclick: () => render() }));
      })),
  );
};

// ---- router ----------------------------------------------------------------------------

export function parseRoute(hash) {
  const parts = String(hash || '').replace(/^#\/?/, '').split('/').filter(Boolean);
  const [name = '', id = null] = parts;
  if (name === 'people' && id) return { name: 'person', id: decodeURIComponent(id) };
  return { name, id: null };
}

function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

async function render() {
  clearTimers();
  let route = parseRoute(location.hash);
  if (!screens[route.name]) route = { name: state.me ? 'skills' : 'start', id: null };
  if (!state.me && !PUBLIC_ROUTES.has(route.name)) route = { name: 'start', id: null };
  if (state.me && route.name === 'start') route = { name: 'skills', id: null };
  state.route = route;
  try { localStorage.setItem(LAST_ROUTE, `#/${route.name === 'person' ? `people/${route.id}` : route.name}`); } catch { /* private mode */ }
  for (const s of document.querySelectorAll('[data-screen]')) s.hidden = true;
  const key = route.name === 'person' ? 'person' : route.name;
  const root = document.querySelector(`[data-screen="${key}"]`);
  root.hidden = false;
  $('#nav').hidden = !state.me;
  for (const a of document.querySelectorAll('[data-nav]')) {
    if (a.dataset.nav === route.name || (route.name === 'person' && a.dataset.nav === 'people')) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  try {
    await screens[route.name](root, route.id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { state.me = null; go('#/start'); return; }
    root.replaceChildren(title('hmm'), h('p', { class: 'lede', text: errorText(e) }));
  }
  window.scrollTo(0, 0);
}

function online() {
  $('#offline').hidden = navigator.onLine;
}

async function boot() {
  window.addEventListener('online', online);
  window.addEventListener('offline', online);
  online();
  const me = document.querySelector('script[data-sw]');
  if ('serviceWorker' in navigator && me) {
    navigator.serviceWorker.register(me.dataset.sw, { scope: me.dataset.scope }).catch(() => {});
  }
  try {
    state.config = await get('/api/config');
    await refreshMe();
  } catch (e) {
    state.config = state.config || { calls_enabled: false, lookup_enabled: false, payments_enabled: false };
    toast(errorText(e));
  }
  if (!location.hash) {
    let last = null;
    try { last = localStorage.getItem(LAST_ROUTE); } catch { /* private mode */ }
    location.replace(last && last.startsWith('#/') ? last : '#/start');
  }
  window.addEventListener('hashchange', render);
  render();
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', boot);
}

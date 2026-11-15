// tacit PWA: the hash router and the screens. Every piece of API data goes into the page with
// textContent or attributes, never as markup.
import { ApiError, del, get, patch, post, put } from './api.js';

const E164 = /^\+[1-9]\d{7,14}$/;
const TAGLINE = 'agents have skills. people have taste. tacit is how it gets around.';
const LAST_ROUTE = 'tacit:last-route'; // the only thing kept in localStorage
const PUBLIC_ROUTES = new Set(['start']);

const state = { me: null, config: null, timers: [], stops: [], route: null, band: null, bands: [16, 74] };

// Parts of the "me" screen added further down (the band, what it notices, the picture).
export const meSections = [];

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

// replaceChildren() would print a null part as the text "null": skip empty parts.
function fill(node, ...kids) {
  node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  return node;
}

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
    return await fn(btn); // the button is passed in: ev.currentTarget is gone after an await
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
  for (const stop of state.stops) stop();
  state.timers = [];
  state.stops = [];
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
    fill(wrap, 
      h('span', { class: 'ask', text: sure }),
      h('button', { type: 'button', class: 'tc-btn', text: 'yes', onclick: (ev) => onYes(ev.currentTarget) }),
      h('button', { type: 'button', class: 'tc-btn quiet', text: 'no', onclick: () => fill(wrap, first) }),
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
  fill(root, 
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
    fill(list, ...(items.length ? items.map(contextCard)
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
  fill(root, 
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
    fill(live, ...fresh.map((k) => h('article', { class: 'tc-card saved' },
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
  fill(root, 
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
  fill(root, title('your skills'), h('p', { class: 'muted', text: 'loading…' }));
  const mine = await get('/api/skills/mine');
  const list = h('div', { class: 'stack' });
  fill(list, ...(mine.length ? mine.map(ownSkillCard)
    : [h('p', { class: 'lede', text: 'No skills yet. Have a short conversation with tacit and they will appear here.' }),
      h('a', { class: 'tc-btn on-ground wide', href: '#/call', text: 'have a conversation' })]));
  fill(root, title('your skills'),
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
      h('button', { type: 'button', class: 'tc-textlink', text: 'edit', onclick: () => fill(card, editForm(s, draw)) }),
      twoStep('remove', 'remove it everywhere?', (b) => act(b, async () => {
        await patch(`/api/skills/${encodeURIComponent(s.id)}`, { status: 'removed' });
        card.remove();
      }), 'tc-textlink'));
    fill(card, ...skillBody(s), jev ? h('p', { class: 'jev', text: jev }) : null, acts);
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

// ---- people, a person, the feed ---------------------------------------------------------

// A PersonRing: a ring of pluses (bigger with more skills) and the first name in handwriting.
function personRing(person, { size = 'sm' } = {}) {
  const px = size === 'lg' ? 120 : 76;
  const cv = h('canvas', { class: 'ring-cv', width: px, height: px, 'aria-hidden': 'true',
    style: `width:${px}px;height:${px}px` });
  const fig = h('figure', { class: `ring ${size}` }, h('div', { class: 'tc-ground ring-ground' }, cv),
    h('figcaption', { class: 'tc-hand ring-name', text: (person.first_name || '').toLowerCase() }));
  requestAnimationFrame(() => drawRing(cv, person.skill_count || 0, size === 'lg' ? 8 : 6));
  return fig;
}

export function ringRadius(skills, cell) {
  return cell * (1.9 + 1.2 * Math.min(1, skills / 8));
}

function drawRing(cv, skills, cell) {
  const T = window.Tacit;
  if (!T || !cv.isConnected) return;
  const p = T.pen(cv, cell);
  T.ring(p.put, T.snap(p.W / 2, cell), T.snap(p.H / 2, cell), ringRadius(skills, cell), cell);
}

screens.people = async function people(root) {
  fill(root, title('people'), h('p', { class: 'muted', text: 'loading…' }));
  const list = await get('/api/people');
  const others = list.filter((p) => !state.me || p.id !== state.me.id);
  fill(root, 
    title('people'),
    h('p', { class: 'lede', text: 'People who published what they know. Follow someone to see their skills in your feed.' }),
    others.length
      ? h('ul', { class: 'people' }, ...others.map((p) => h('li', {},
        h('a', { class: 'person-link', href: `#/people/${encodeURIComponent(p.id)}` },
          personRing(p),
          h('span', { class: 'person-meta' },
            p.headline ? h('span', { class: 'headline', text: p.headline }) : null,
            h('span', { class: 'small', text: `${p.skill_count} skill${p.skill_count === 1 ? '' : 's'} · ${p.follower_count} follower${p.follower_count === 1 ? '' : 's'}${p.following ? ' · following' : ''}` }))))))
      : h('p', { class: 'muted', text: 'Nobody has published a skill yet.' }),
  );
};


export function price(cents) {
  const d = (Number(cents) || 0) / 100;
  return `$${Number.isInteger(d) ? d : d.toFixed(2)}`;
}

// ---- a person's profile card (the team's design: Ana's and Ziad's profile pages) ----------

function sameDayIso(iso) {
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && sameDay(d, new Date());
}

const SKILL_FROM = { interview: 'from a call', conversation: 'heard' };

function avatar(p) {
  if (p.portrait) return portraitPatch(p.portrait, { small: true, colors: p.portrait_colors, tile: true });
  return h('span', { class: 'face ring avatar-ring', 'aria-hidden': 'true', text: (p.first_name || '?').charAt(0).toUpperCase() });
}

function chips(list, outline) {
  return h('dd', { class: 'chips' }, ...list.map((c) => h('span', { class: `chip${outline ? ' outline' : ''}`, text: c })));
}

function metLine(iso) {
  const d = new Date(iso);
  return `handshake · ${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${clock(iso).toLowerCase()}`;
}

function profileSkill(s, owner) {
  const more = h('div', { class: 'skill-more', hidden: true },
    ...(s.locked ? [h('p', { class: 'muted-ink', text: 'for followers who unlocked this person\'s skills' })]
      : [s.verdict ? h('p', { class: 'verdict', text: s.verdict }) : null,
        s.reason ? h('p', { class: 'reason' }, h('em', { text: 'because ' }), s.reason) : null,
        s.quote ? h('p', { class: 'tc-said quote', text: `“${s.quote}”` }) : null]));
  const tag = sameDayIso(s.created_at) ? h('span', { class: 'today', text: 'today' })
    : h('span', { class: 'from', text: s.locked ? 'followers' : (SKILL_FROM[s.source] || '') });
  const btn = h('button', { type: 'button', class: 'skill-line', 'aria-expanded': 'false' },
    h('span', { class: 'plus', 'aria-hidden': 'true', text: '+' }), h('span', { class: 'skill-title', text: s.title }), tag);
  btn.addEventListener('click', () => {
    more.hidden = !more.hidden;
    btn.setAttribute('aria-expanded', String(!more.hidden));
  });
  return h('li', {}, btn, more);
}

// From "how others see you" (#/people/<me>), the avatar goes to #/me and scrolls to the picture.
let wantPicture = false;
function goToPicture() {
  wantPicture = true;
  location.hash = '#/me';
}

export function profileCard(p, { isMe = false } = {}) {
  const n = (x, one, many) => h('span', { class: 'stat' }, h('b', { text: String(x) }), x === 1 ? one : many);
  const rows = [];
  if (p.location) rows.push(h('dt', { text: 'based in' }), h('dd', { text: p.location }));
  if (p.company) rows.push(h('dt', { text: 'company' }), h('dd', { text: p.company }));
  if (p.met_at) rows.push(h('dt', { text: 'met at' }), h('dd', { text: metLine(p.met_at) }));
  if (p.expertise && p.expertise.length) rows.push(h('dt', { text: 'expertise' }), chips(p.expertise, false));
  if (p.worth_knowing && p.worth_knowing.length) rows.push(h('dt', { text: 'worth knowing' }), chips(p.worth_knowing, true));
  const skills = p.skills || [];
  return h('article', { class: 'tc-card profile-card' },
    h('div', { class: 'who-row' }, isMe
      ? h('button', { type: 'button', class: 'avatar-btn', 'aria-label': p.portrait ? 'change your picture' : 'make your picture',
        onclick: () => {
          if (location.hash !== '#/me') { goToPicture(); return; }
          const el = document.getElementById('your-picture');
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } }, avatar(p), h('span', { class: 'avatar-hint', text: p.portrait ? 'change' : 'add picture' }))
      : avatar(p),
      h('div', {}, h('p', { class: 'profile-name', text: p.first_name }), h('p', { class: 'handle', text: `@${p.handle || ''}` }))),
    p.headline ? h('p', { class: 'profile-headline', text: p.headline }) : null,
    h('p', { class: 'stats' }, n(p.skill_count, 'skill', 'skills'), n(p.post_count || 0, 'post', 'posts'),
      n(p.recommendation_count || 0, 'recommendation', 'recommendations')),
    rows.length ? h('dl', { class: 'profile-rows' }, ...rows)
      : (isMe ? h('p', { class: 'muted-ink', text: 'Add where you\'re based, your company and what you know, below.' }) : null),
    skills.length ? h('ul', { class: 'profile-skills' }, ...skills.map((s) => profileSkill(s, isMe)))
      : h('p', { class: 'muted-ink', text: isMe ? 'No published skills yet: publish one in your skills.' : 'No published skills yet.' }),
    p.recommends && p.recommends.length ? h('dl', { class: 'profile-rows' },
      h('dt', { text: 'recommends' }), chips(p.recommends, true)) : null);
}

screens.person = async function person(root, id, params) {
  fill(root, h('p', { class: 'muted', text: 'loading…' }));
  if (params && params.get('paid') === '1') toast('Thank you. Their followers-only skills unlock as soon as Stripe confirms.');
  const p = await get(`/api/people/${encodeURIComponent(id)}`);
  const isMe = state.me && p.id === state.me.id;
  const locked = p.skills.filter((s) => s.locked).length;
  const acts = h('div', { class: 'profile-acts' });
  if (!isMe) {
    acts.append(p.following
      ? h('button', { type: 'button', class: 'tc-btn quiet', text: `unfollow ${p.first_name}`, onclick: (ev) => act(ev.currentTarget, async () => {
        await del(`/api/follow/${encodeURIComponent(p.id)}`);
        render();
      }) })
      : h('button', { type: 'button', class: 'tc-btn', text: `Follow ${p.first_name}`, onclick: (ev) => act(ev.currentTarget, async () => {
        await post(`/api/follow/${encodeURIComponent(p.id)}`);
        render();
      }) }),
    h('a', { class: 'tc-btn quiet', href: '#/connect', text: 'Connect in person' }));
    if (locked && state.config.payments_enabled && !p.paid) {
      acts.append(h('button', { type: 'button', class: 'tc-btn quiet', text: `unlock followers-only skills for ${price(state.config.follow_price_cents)}`,
        onclick: (ev) => act(ev.currentTarget, async () => {
          const { url } = await post(`/api/follow/${encodeURIComponent(p.id)}/checkout`);
          if (typeof url === 'string' && url.startsWith('https://')) location.assign(url);
        }) }));
    }
  }
  const card = profileCard(p, { isMe });
  if (!isMe) card.append(acts);
  fill(root, h('a', { class: 'back', href: '#/people', text: '← network' }), card);
};

// ---- the feed: lines, not cards (the team's design, screens/feed) ---------------------------

const MADE = { writing: 'wrote', drawing: 'sketched', whiteboard: 'drew on a whiteboard', making: 'made something' };

export function creativeLine(item) {
  const who = (item.person && item.person.first_name || 'someone').toLowerCase();
  const m = item.minutes || 0;
  return `${who} ${MADE[item.kind] || 'made something'} for ${m} minute${m === 1 ? '' : 's'}`;
}

const POST_WORDS = { recommendation: 'recommends', lesson: 'learned', idea: 'had an idea' };
const HEARD_WORDS = { advice_given: 'gave advice', explanation: 'explained how', lesson: 'learned',
  demonstration: 'showed how', idea: 'had an idea', recommendation: 'recommended', decision: 'decided',
  commitment: 'committed to something', question: 'asked' };

// The four feed tabs and which item types each shows.
export const FEED_TABS = {
  everything: null,
  advice: new Set(['picked_up', 'post', 'heard']),
  skills: new Set(['skill', 'pass']),
  people: new Set(['pass', 'creative', 'connected']),
};

export function inTab(item, tab) {
  const kinds = FEED_TABS[tab];
  return !kinds || kinds.has(item.type);
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function dayLabel(iso, now = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  if (sameDay(d, now)) return 'today';
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (sameDay(d, y)) return 'yesterday';
  return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' }).toLowerCase();
}

function timeLabel(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return sameDay(d, new Date()) ? clock(iso).toLowerCase() : dayLabel(iso);
}

// A person as a small dotted ring with their initial (the design's fallback for a portrait).
function face(name, big = false) {
  const initial = String(name || '?').trim().charAt(0).toUpperCase() || '?';
  return h('span', { class: `face ring${big ? ' big' : ''}`, 'aria-hidden': 'true', text: initial });
}

function head(parts, iso) {
  return h('p', { class: 'head' }, ...parts.map((p) => (p && p.name !== undefined
    ? h('b', { class: 'name', text: p.name }) : h('span', { text: p }))), h('time', { datetime: iso, text: timeLabel(iso) }));
}

function story(who, headParts, iso, ...body) {
  return h('article', { class: 'story' }, face(who), h('div', { class: 'body' }, head(headParts, iso), ...body));
}

function because(text) {
  return text ? h('p', { class: 'why' }, h('i', { text: 'because' }), text.replace(/^because\s+/i, '')) : null;
}

function said(text) {
  return text ? h('p', { class: 'said', text: `“${text}”` }) : null;
}

function nameOf(p, fallback = 'someone') {
  return (p && p.first_name) || fallback;
}

export function feedItem(item) {
  if (item.type === 'picked_up') {
    const b = item.body || {};
    const giver = nameOf(item.giver, 'someone you talked with');
    const momentId = String(item.id).replace(/^picked_up:/, '');
    const acts = h('p', { class: 'acts' },
      h('button', { type: 'button', text: 'keep it', onclick: (ev) => act(ev.currentTarget, async (btn) => {
        await patch(`/api/moments/${encodeURIComponent(momentId)}`, { status: 'kept' });
        btn.textContent = 'kept';
      }) }),
      h('button', { type: 'button', class: 'soft', text: 'dismiss', onclick: (ev) => act(ev.currentTarget, async (btn) => {
        await patch(`/api/moments/${encodeURIComponent(momentId)}`, { status: 'dismissed' });
        btn.closest('.story').remove();
      }) }),
      h('span', { class: 'note', text: 'only you see this' }));
    return story(giver, [{ name: giver }, 'gave you advice · heard'], item.at,
      h('h2', { class: 'line', text: item.title || b.title || b.verdict || '' }),
      b.verdict && b.verdict !== item.title ? h('p', { class: 'note', text: b.verdict }) : null,
      because(b.reason), said(b.quote), acts);
  }
  if (item.type === 'skill') {
    const s = item.skill;
    const who = nameOf(item.person);
    return story(who, [{ name: who }, 'shared a new skill'], item.at,
      h('h2', { class: 'line', text: s.title }),
      s.locked ? h('p', { class: 'note' }, 'for followers who unlocked it · ',
        h('a', { href: `#/people/${encodeURIComponent(item.person.id)}`, class: 'link', text: 'see how' }))
        : [s.verdict ? h('p', { class: 'note', text: s.verdict }) : null, because(s.reason), said(s.quote)]);
  }
  if (item.type === 'pass') {
    const giver = nameOf(item.giver);
    const receiver = nameOf(item.receiver);
    const youGave = state.me && item.giver && item.giver.id === state.me.id;
    const youGot = state.me && item.receiver && item.receiver.id === state.me.id;
    return h('article', { class: `story pass${item.lit ? ' lit' : ''}` }, face(giver),
      h('div', { class: 'body' },
        head([{ name: youGave ? 'You' : giver }, 'passed a skill to', { name: youGot ? 'you' : receiver }], item.at),
        h('h2', { class: 'line', text: item.skill ? item.skill.title : 'a skill' }),
        h('p', { class: 'note', text: 'you were in the same conversation, both wearing tacit' })));
  }
  if (item.type === 'heard') {
    const b = item.body || {};
    const verb = HEARD_WORDS[item.kind] || 'said something';
    const ready = ['title', 'verdict', 'what', 'thing', 'question', 'idea'].some((k) => b[k]);
    const line = ready ? (b.title || b.what || b.thing || b.question || b.idea || item.title) : (KIND_WORDS[item.kind] || item.kind);
    return story('You', [{ name: 'You' }, `${verb} · heard`], item.at,
      h('h2', { class: 'line', text: line }),
      ready && b.verdict && b.verdict !== line ? h('p', { class: 'note', text: b.verdict }) : null,
      ready ? because(b.reason || b.why) : h('p', { class: 'note', text: 'The details aren\'t filled in yet; they will be as soon as the band\'s AI step is available.' }),
      h('p', { class: 'acts' }, h('a', { class: 'link', href: '#/moments', text: 'what was said' }),
        h('span', { class: 'note', text: 'only you see this' })));
  }
  if (item.type === 'connected') {
    const who = nameOf(item.person);
    return story('You', [{ name: 'You' }, 'and', { name: who }, 'connected · handshake'], item.at,
      h('h2', { class: 'line', text: `You shook hands with ${who}` }),
      h('p', { class: 'note' }, 'You now follow each other. ',
        h('a', { class: 'link', href: `#/people/${encodeURIComponent(item.person.id)}`, text: `see ${who}'s skills` })));
  }
  if (item.type === 'creative') {
    const who = nameOf(item.person);
    return story(who, [{ name: who }, (MADE[item.kind] || 'made something')], item.at,
      h('h2', { class: 'line', text: `for ${item.minutes || 0} minute${item.minutes === 1 ? '' : 's'}` }));
  }
  if (item.type === 'post') {
    const b = item.body || {};
    const who = nameOf(item.person);
    return story(who, [{ name: who }, POST_WORDS[item.kind] || 'shared'], item.at,
      h('h2', { class: 'line', text: item.title || b.thing || b.idea || '' }),
      because(b.why || b.reason), b.verdict ? h('p', { class: 'note', text: b.verdict }) : null);
  }
  return null;
}

function sideColumn(items, following) {
  const day = Date.now() - 24 * 3600 * 1000;
  const met = new Map();
  for (const i of items) {
    if (i.type === 'connected' && new Date(i.at).getTime() >= day && i.person) {
      met.set(i.person.id, { ...i.person, how: 'connected · handshake' });
      continue;
    }
    if (i.type !== 'pass' || new Date(i.at).getTime() < day) continue;
    for (const p of [i.giver, i.receiver]) {
      if (p && p.id && (!state.me || p.id !== state.me.id)) met.set(p.id, { ...p, how: 'same conversation' });
    }
  }
  const people = met.size ? [...met.values()]
    : following.map((p) => ({ id: p.id, first_name: p.first_name, how: p.paid ? 'you unlocked their skills' : 'you follow their skills' }));
  const recs = items.filter((i) => i.type === 'post' && i.kind === 'recommendation');
  return h('aside', { class: 'col-people' },
    people.length ? h('section', { class: 'met' },
      h('p', { class: 'label', text: met.size ? 'people you met today' : 'people you follow' }),
      h('ul', {}, ...people.slice(0, 8).map((p) => h('li', {},
        h('a', { class: 'met-link', href: `#/people/${encodeURIComponent(p.id)}` }, face(p.first_name, true),
          h('p', {}, h('b', { class: 'name', text: p.first_name }), h('small', { text: p.how }))))))) : null,
    recs.length ? h('section', { class: 'recommends' },
      h('p', { class: 'label', text: 'your network recommends' }),
      h('ul', {}, ...recs.slice(0, 6).map((r) => h('li', {},
        h('a', { href: `#/people/${encodeURIComponent(r.person.id)}`, text: r.title || (r.body && r.body.thing) || '' }), ' ',
        h('small', { text: nameOf(r.person) })))),
      h('p', { class: 'hint', text: 'What people you follow said was worth it.' })) : null);
}

screens.feed = async function feed(root, _id, params) {
  const tab = params && FEED_TABS[params.get('tab')] !== undefined ? params.get('tab') : 'everything';
  fill(root, h('h1', { class: 'title', text: 'today in your network' }), h('p', { class: 'label', text: 'loading…' }));
  const [items, people] = await Promise.all([get('/api/feed'), get('/api/people').catch(() => [])]);
  const following = people.filter((p) => p.following);
  const shown = items.filter((i) => inTab(i, tab));
  const lines = [];
  let lastDay = null;
  for (const i of shown) {
    const day = dayLabel(i.at);
    if (day !== lastDay) { lines.push(h('p', { class: 'label', text: day })); lastDay = day; }
    const line = feedItem(i);
    if (line) lines.push(line);
  }
  const tabs = h('nav', { class: 'tabs-feed', 'aria-label': 'feed' }, ...Object.keys(FEED_TABS).map((t) => h('a', {
    href: t === 'everything' ? '#/feed' : `#/feed?tab=${t}`, class: t === tab ? 'on' : null,
    'aria-current': t === tab ? 'true' : null, text: t })));
  const empty = items.length
    ? h('p', { class: 'note', text: `Nothing under "${tab}" yet.` })
    : h('div', { class: 'stack' },
      h('p', { class: 'note', text: 'Nothing here yet. Follow people to see the skills they publish; advice you hear with your band shows up here too, only for you.' }),
      h('a', { class: 'tc-btn on-ground', href: '#/people', text: 'find people' }));
  fill(root, h('div', { class: 'feed-layout' },
    h('div', { class: 'col-feed' },
      h('h1', { class: 'title', text: 'today in your network' }),
      tabs,
      h('div', { class: 'stories' }, ...(lines.length ? lines : [empty]))),
    sideColumn(items, following)));
};

// ---- + connect: in person, by following, or by your context (screens in the team's design) --

screens.connect = async function connect(root) {
  fill(root, h('h1', { class: 'title', text: 'connect' }), h('p', { class: 'label', text: 'loading…' }));
  const [people] = await Promise.all([get('/api/people').catch(() => []), pollBand()]);
  const others = people.filter((p) => !state.me || p.id !== state.me.id);
  const b = state.band;
  const me = firstName(state.me.name) || 'You';
  const inPerson = h('div', { class: 'tc-card form connect-card' },
    h('h2', { class: 'card-title', text: 'connect in person' }),
    h('p', { class: 'band-row' }, h('b', { class: 'hand', text: me }),
      h('span', { class: 'band-badge', text: b ? `band ${b.band}` : 'no band yet' })),
    h('p', { class: 'sub', text: 'what happens' }),
    h('p', { text: 'Talk with someone who also wears tacit. When one of you explains how they do something, it becomes their draft skill, and a pass to the other once they publish it.' }),
    h('p', { class: 'sub', text: 'what stays yours' }),
    h('p', { text: 'Recordings, other people\'s words, and anything you haven\'t shared.' }),
    h('div', { class: 'acts' }, b
      ? h('a', { class: 'tc-btn', href: '#/me', text: b.listening ? 'your band is listening' : 'your band' })
      : h('a', { class: 'tc-btn', href: '#/me', text: 'connect your band' })));
  const follow = h('div', { class: 'tc-card form connect-card quiet-card' },
    h('h2', { class: 'sub', text: 'no band on the other side?' }),
    h('p', { text: 'Follow instead. It is one-way: their public skills reach your feed, and they see that you follow.' }),
    others.length ? h('ul', { class: 'follow-list' }, ...others.slice(0, 12).map((p) => h('li', {},
      h('a', { class: 'hand', href: `#/people/${encodeURIComponent(p.id)}`, text: p.first_name }),
      p.following ? h('span', { class: 'note-ink', text: 'following' })
        : h('button', { type: 'button', class: 'tc-btn quiet', text: `follow ${p.first_name}'s skills`, onclick: (ev) => act(ev.currentTarget, async (btn) => {
          await post(`/api/follow/${encodeURIComponent(p.id)}`);
          btn.replaceWith(h('span', { class: 'note-ink', text: 'following' }));
        }) }))))
      : h('p', { class: 'note-ink', text: 'Nobody has published a skill yet.' }));
  const yours = h('div', { class: 'tc-card form connect-card quiet-card' },
    h('h2', { class: 'sub', text: 'your own context' }),
    h('p', { text: 'What is public about you, and a short conversation with tacit, start your profile.' }),
    h('div', { class: 'acts' },
      h('a', { class: 'tc-btn quiet', href: '#/context', text: 'connect your context' }),
      h('a', { class: 'tc-btn quiet', href: '#/call', text: 'have a conversation' })));
  fill(root, h('h1', { class: 'title', text: 'connect' }), inPerson, follow, yours);
};

// ---- your transcript: what your band heard, live, only for you (kept 24 h) -------------------

export function speakerLabel(seg) {
  if (seg.you) return 'you';
  return seg.speaker === null || seg.speaker === undefined ? 'someone' : `speaker ${seg.speaker + 1}`;
}

screens.transcript = async function transcript(root) {
  const list = h('ol', { class: 'transcript', 'aria-live': 'polite' });
  const seen = new Set();
  let last = null;
  const empty = h('p', { class: 'note-on-ground', text: 'Nothing yet. Start your band\'s bridge; lines appear a few seconds after someone finishes a sentence.' });
  const nearBottom = () => window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
  const add = (seg) => {
    if (seen.has(seg.id)) return;
    seen.add(seg.id);
    const li = h('li', { class: seg.you ? 'you' : null },
      h('span', { class: 'who' }, h('b', { text: speakerLabel(seg) }), h('time', { datetime: seg.started_at, text: clock(seg.started_at) })),
      h('p', { text: seg.text }));
    // keep the lines in time order even when one arrives late
    const after = [...list.children].find((x) => x.dataset.at > seg.started_at);
    li.dataset.at = seg.started_at;
    if (after) list.insertBefore(li, after); else list.append(li);
    if (!last || seg.ended_at > last) last = seg.ended_at;
  };
  const load = async () => {
    const stick = nearBottom();
    const q = last ? `?since=${encodeURIComponent(new Date(new Date(last).getTime() - 15000).toISOString())}` : '';
    const out = await get(`/api/transcript${q}`);
    out.segments.forEach(add);
    empty.hidden = list.children.length > 0;
    status.textContent = state.band && state.band.listening ? 'listening now' : state.band && state.band.muted ? 'muted' : 'not listening';
    if (stick && out.segments.length) window.scrollTo(0, document.body.scrollHeight);
  };
  const status = h('span', { class: 'live' });
  fill(root,
    title('your transcript'),
    h('p', { class: 'lede' }, 'Everything your band heard, as text. ', h('b', { text: 'Only you see this.' }),
      ' Lines are deleted after 24 hours, and a mute removes the last 15 seconds.'),
    h('p', { class: 'transcript-bar' }, status,
      twoStep('delete my transcript', 'Delete every line now?', (btn) => act(btn, async () => {
        await del('/api/transcript');
        fill(list);
        seen.clear();
        last = null;
        empty.hidden = false;
        toast('Your transcript is deleted.');
      }), 'tc-textlink on-ground-link')),
    empty, list);
  await load();
  window.scrollTo(0, document.body.scrollHeight);
  every(2500, () => load().catch(() => {}));
};

// ---- the band: moments, "your band", the ListeningPill -------------------------------------

export const KIND_WORDS = {
  stop_request: 'asked to stop', conversation: 'a conversation', advice_given: 'advice you gave',
  advice_received: 'advice you got', explanation: 'an explanation', lesson: 'a lesson',
  question: 'a question you asked', decision: 'a decision', commitment: 'a commitment',
  recommendation: 'a recommendation', idea: 'an idea', presenting: 'presenting',
  writing: 'writing', drawing: 'drawing', whiteboard: 'at the whiteboard', typing: 'typing',
  making: 'making something', walking_meeting: 'a walking meeting', demonstration: 'a demonstration',
  kept: 'a minute you kept', handshake: 'a handshake',
};
const SHAREABLE = new Set(['recommendation', 'lesson', 'idea']);

function clock(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function hourKey(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}, ${d.toLocaleTimeString([], { hour: '2-digit' })}`;
}

// The labelled fields of a moment, from what the band extracted (never invented on screen).
export function momentFields(m) {
  const b = m.body || {};
  const rows = [];
  const add = (label, value) => {
    if (typeof value === 'string' && value.trim()) rows.push([label, value.trim()]);
    else if (Array.isArray(value) && value.length) rows.push([label, value]);
  };
  add('what to do', b.verdict);
  add('why', b.reason);
  add('steps', (b.steps || []).filter(Boolean));
  if (b.quote) rows.push(['in their words', `“${b.quote}”`, 'said']);
  add('what', b.what);
  add('who', b.who);
  add('when', b.when_text);
  add('why', b.why);
  add('the thing', b.thing);
  add('kind of thing', b.kind);
  add('the question', b.question);
  add('about', b.topic);
  add('the idea', b.idea);
  add('with', b.with);
  if (Array.isArray(b.matches) && b.matches.length) {
    rows.push(['people who know', b.matches.map((x) => `${x.first_name}: ${x.title}`)]);
  }
  if (Array.isArray(b.found) && m.kind === 'kept') {
    rows.push(['found in that minute', b.found.length ? b.found.map((k) => KIND_WORDS[k] || k) : ['nothing specific']]);
  }
  return rows;
}

export function sureWord(c) {
  const p = Math.round((c || 0) * 100);
  return `${p >= 85 ? 'sure' : p >= 70 ? 'fairly sure' : 'a guess'} (${p}%)`;
}

const SOURCE_WORDS = { audio: 'heard by the band', motion: 'from how your wrist moved', both: 'heard and from your wrist' };

export function duration(startIso, endIso) {
  const s = Math.max(0, Math.round((new Date(endIso) - new Date(startIso)) / 1000));
  if (s < 60) return s ? `${s} s` : 'a moment';
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function fieldList(rows) {
  if (!rows.length) return null;
  return h('dl', { class: 'fields' }, ...rows.flatMap(([label, value, kind]) => [
    h('dt', { text: label }),
    h('dd', { class: kind || null }, Array.isArray(value)
      ? h(label === 'steps' ? 'ol' : 'ul', {}, ...value.map((v) => h('li', { text: v })))
      : value),
  ]));
}

async function momentMore(m, box) {
  const d = await get(`/api/moments/${encodeURIComponent(m.id)}`);
  const parts = [];
  if (d.lines.length) {
    parts.push(h('p', { class: 'sub-label', text: 'what was said' }),
      h('ol', { class: 'transcript mini' }, ...d.lines.map((l) => h('li', { class: l.you ? 'you' : null },
        h('span', { class: 'who' }, h('b', { text: speakerLabel(l) }), h('time', { text: clock(l.at) })),
        h('p', { text: l.text })))));
  } else if (d.lines_expected) {
    parts.push(h('p', { class: 'note-ink', text: 'The words behind this moment are gone: transcripts are kept for 24 hours, and a mute removes the last 15 seconds.' }));
  } else {
    parts.push(h('p', { class: 'note-ink', text: m.source === 'motion' ? 'This came from how your wrist moved; no words are kept with it.' : 'No words are kept with this moment.' }));
  }
  if (d.skill) {
    const jev = jevLine(d.skill.jev_specific);
    parts.push(h('p', { class: 'sub-label', text: 'the draft skill it made' }),
      h('p', {}, h('a', { href: '#/skills', class: 'link-ink', text: d.skill.title }), ` · ${d.skill.status}${jev ? ` · ${jev}` : ''}`));
  }
  for (const p of d.passes) {
    parts.push(h('p', { class: 'sub-label', text: 'a pass' }),
      h('p', { text: p.you_gave ? `You passed it to ${p.receiver}.` : `${p.giver} passed it to you.` }));
  }
  fill(box, ...parts);
}

function momentCard(m) {
  const card = h('article', { class: `tc-card moment ${m.status}` });
  const draw = () => {
    const acts = h('div', { class: 'row' });
    const set = (status) => (ev) => act(ev.currentTarget, async () => {
      Object.assign(m, await patch(`/api/moments/${encodeURIComponent(m.id)}`, { status }));
      draw();
    });
    const more = h('div', { class: 'more', hidden: true });
    const toggle = h('button', { type: 'button', class: 'tc-textlink', text: 'what was said', 'aria-expanded': 'false' });
    toggle.addEventListener('click', () => act(toggle, async () => {
      const open = more.hidden;
      if (open && !more.childNodes.length) await momentMore(m, more);
      more.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'hide' : 'what was said';
    }));
    if (m.status !== 'kept') acts.append(h('button', { type: 'button', class: 'tc-btn quiet', text: 'keep', onclick: set('kept') }));
    if (m.status !== 'dismissed') acts.append(h('button', { type: 'button', class: 'tc-btn quiet', text: 'dismiss', onclick: set('dismissed') }));
    if (SHAREABLE.has(m.kind) && m.status !== 'shared') {
      acts.append(h('button', { type: 'button', class: 'tc-btn', text: 'share as a post', onclick: set('shared') }));
    }
    acts.append(toggle);
    const facts = [clock(m.started_at), duration(m.started_at, m.ended_at), SOURCE_WORDS[m.source] || m.source, sureWord(m.confidence)];
    fill(card,
      h('div', { class: 'top' }, h('span', { class: 'tag-phrase', text: KIND_WORDS[m.kind] || m.kind }),
        m.status === 'kept' ? h('span', { class: 'when', text: 'kept' }) : null),
      m.title && m.title !== KIND_WORDS[m.kind] ? h('h3', { class: 'card-title', text: m.title }) : null,
      h('p', { class: 'facts', text: facts.filter(Boolean).join(' · ') }),
      fieldList(momentFields(m)),
      m.status === 'shared' ? h('p', { class: 'only-you', text: 'shared with your followers' }) : h('p', { class: 'only-you', text: 'only you see this' }),
      acts, more);
  };
  draw();
  return card;
}

screens.moments = async function moments(root) {
  fill(root, title('your moments'), h('p', { class: 'muted', text: 'loading…' }));
  const list = (await get('/api/moments')).filter((m) => m.status !== 'dismissed');
  const groups = [];
  for (const m of list) {
    const key = hourKey(m.started_at);
    if (!groups.length || groups[groups.length - 1].key !== key) groups.push({ key, items: [] });
    groups[groups.length - 1].items.push(m);
  }
  fill(root, 
    title('your moments'),
    h('p', { class: 'lede', text: 'What your band noticed. Only you see these, unless you share one.' }),
    ...(groups.length ? groups.map((g) => h('div', { class: 'stack' }, phrase(g.key), ...g.items.map(momentCard)))
      : [h('p', { class: 'muted', text: 'Nothing yet. Connect your band in "me".' })]),
  );
};

// The ListeningPill: only while the bridge reports "listening". It is the only blue in the app.
export function pillState(band) {
  if (!band || !band.connected) return null;
  if (band.listening) return 'listening';
  if (band.muted) return 'muted';
  return null;
}

function showPill(band) {
  const pill = $('#pill');
  const s = pillState(band);
  pill.hidden = !s;
  pill.className = s === 'listening' ? 'listen-pill tc-pill' : `listen-pill${s === 'muted' ? ' muted' : ''}`;
  if (s === 'listening') {
    fill(pill, h('span', { class: 'tc-bud', 'aria-hidden': 'true' }, ...Array.from({ length: 9 }, () => h('i'))), 'listening');
  } else if (s === 'muted') {
    fill(pill, 'muted');
  } else {
    fill(pill, );
  }
}

async function pollBand() {
  if (!state.me) { showPill(null); return null; }
  try {
    const out = await get('/api/band');
    state.band = out.band;
    state.bands = out.bands;
    showPill(out.band);
    return out.band;
  } catch {
    return state.band || null;
  }
}

function bandSection() {
  const wrap = h('div', { class: 'stack' }, phrase('your band'));
  const card = h('div', { class: 'tc-card form band' });
  wrap.append(card);
  const draw = () => {
    const b = state.band;
    if (!b) {
      const picks = h('div', { class: 'row' }, ...(state.bands || [16, 74]).map((n) => h('button', {
        type: 'button', class: 'tc-btn quiet', text: `band ${n}`, onclick: (ev) => act(ev.currentTarget, async () => {
          const out = await post('/api/band/pair', { band: n });
          await pollBand();
          draw();
          card.prepend(tokenBox(out));
        }) })));
      fill(card, h('p', { text: 'Which band is yours? The number is on its bag.' }), picks);
      return;
    }
    const status = !b.online ? 'the bridge is not running' : !b.connected ? 'the bridge can\'t see the band'
      : b.listening ? 'listening' : b.muted ? 'muted' : 'connected, not listening';
    fill(card, 
      h('p', { class: 'band-status' }, h('b', { text: `band ${b.band}: ` }), status,
        typeof b.battery === 'number' ? ` · battery ${Math.round(b.battery)}%` : ''),
      h('button', { type: 'button', class: 'tc-btn big', text: b.muted ? 'unmute' : 'mute',
        'aria-pressed': String(Boolean(b.muted)),
        onclick: (ev) => act(ev.currentTarget, async () => {
          const out = await post('/api/band/mute', { muted: !b.muted });
          state.band = out.band;
          showPill(out.band);
          draw();
        }) }),
      b.pending ? h('p', { class: 'muted-ink', text: 'sent; the band follows within two seconds' }) : null,
      h('ul', { class: 'gestures' },
        h('li', { text: 'Draw an X or a figure 8 in the air to mute.' }),
        h('li', { text: 'The same again, then a double-tap, to unmute.' }),
        h('li', { text: 'Double-tap to keep the last minute.' }),
        h('li', { text: 'Blue light on the band means it is listening. Tell the people around you.' })),
      twoStep('disconnect this band', 'Disconnect the band? The bridge stops uploading.', (btn) => act(btn, async () => {
        await del('/api/band');
        state.band = null;
        showPill(null);
        draw();
      }), 'tc-textlink'));
  };
  draw();
  return wrap;
}

function tokenBox(out) {
  const text = out.env.join('\n');
  return h('div', { class: 'token' },
    h('p', { text: 'Put these lines in the bridge\'s .env. The token is shown only now.' }),
    h('pre', { class: 'tc-path', text }),
    navigator.clipboard ? h('button', { type: 'button', class: 'tc-btn quiet', text: 'copy',
      onclick: () => navigator.clipboard.writeText(text).then(() => toast('Copied.'), () => {}) }) : null);
}

function kindsSection() {
  const off = new Set(state.me.kinds_off || []);
  const kinds = (state.config.kinds || []).filter((k) => k !== 'stop_request');
  const boxes = kinds.map((k) => {
    const box = h('input', { type: 'checkbox', checked: !off.has(k), value: k });
    box.addEventListener('change', () => act(box, async () => {
      const now = boxes.filter((b) => !b.checked).map((b) => b.value);
      state.me = await patch('/api/me', { kinds_off: now });
    }));
    return box;
  });
  const share = h('input', { type: 'checkbox', checked: Boolean(state.me.share_creative) });
  share.addEventListener('change', () => act(share, async () => {
    state.me = await patch('/api/me', { share_creative: share.checked });
  }));
  return h('div', { class: 'stack' }, phrase('what the band notices'),
    h('div', { class: 'tc-card form kinds' },
      ...boxes.map((b, i) => h('label', { class: 'check' }, b, h('span', { text: KIND_WORDS[kinds[i]] || kinds[i] }))),
      h('p', { class: 'note', text: 'Anyone saying "stop recording" always mutes the band.' }),
      h('label', { class: 'check' }, share, h('span', { text: 'share creative sessions ("ana sketched for 25 minutes", nothing more)' }))));
}

meSections.push(bandSection, kindsSection);


// ---- the dot portrait (SPEC §17): drawn with the landing page's face() on lavender ----------

export function portraitPatch(rows, { small = false, colors = null, tile = false } = {}) {
  const cv = h('canvas', { class: 'face-cv', 'aria-hidden': 'true' });
  // face() (vendor/face.js) reads --ink (hair, eyes), --pollen (skin), --glyph (clothes)
  if (colors) {
    const map = { hair: '--ink', skin: '--pollen', clothes: '--glyph' };
    for (const [k, v] of Object.entries(colors)) if (map[k] && /^#[0-9a-f]{6}$/.test(v)) cv.style.setProperty(map[k], v);
  }
  const patch = h('div', { class: `tc-ground portrait${small ? ' small' : ''}${tile ? ' tile' : ''}`, role: 'img', 'aria-label': 'picture in dots' }, cv);
  requestAnimationFrame(() => {
    if (cv.isConnected && window.TacitFace) state.stops.push(window.TacitFace.draw(cv, rows));
  });
  return patch;
}


const PHOTO_MAX_PX = 1024;
const PHOTO_MAX_CHARS = 1500000;

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new ApiError(0, "That photo couldn't be read."));
    r.readAsDataURL(file);
  });
}

// Shrink a photo to at most 1024 px as a JPEG data URL, in a canvas; it never leaves memory
// except in the one request to the server.
export async function shrinkPhoto(file) {
  const src = await readAsDataURL(file);
  const img = await new Promise((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new ApiError(0, "That photo couldn't be read."));
    i.src = src;
  });
  const scale = Math.min(1, PHOTO_MAX_PX / Math.max(img.naturalWidth, img.naturalHeight));
  const cv = document.createElement('canvas');
  cv.width = Math.max(1, Math.round(img.naturalWidth * scale));
  cv.height = Math.max(1, Math.round(img.naturalHeight * scale));
  cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
  for (const q of [0.85, 0.7, 0.5]) {
    const out = cv.toDataURL('image/jpeg', q);
    if (out.length <= PHOTO_MAX_CHARS) return out;
  }
  throw new ApiError(413, 'That photo is too big.');
}

function pictureSection() {
  const card = h('div', { class: 'tc-card form picture' });
  const candidates = h('div', { class: 'candidates' });
  let mode = 'words';
  const words = h('label', {}, h('span', { text: 'how would you like to look?' }),
    h('textarea', { name: 'description', maxlength: 300, rows: 3, placeholder: 'short curly hair, round glasses, a green jumper' }));
  const fileInput = h('input', { type: 'file', accept: 'image/*', capture: 'user', name: 'photo' });
  const consent = h('input', { type: 'checkbox', name: 'photo_consent' });
  const photo = h('div', { class: 'stack', hidden: true },
    h('label', {}, h('span', { text: 'a photo of yourself' }), fileInput),
    h('label', { class: 'check' }, consent,
      h('span', { text: "This is a photo of me. Send it to MiniMax to make my picture. tacit doesn't keep the photo." })));
  const pick = (m) => () => {
    mode = m;
    words.hidden = false;
    photo.hidden = m !== 'photo';
    for (const b of modeRow.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.mode === m));
  };
  const modeRow = h('div', { class: 'row' },
    h('button', { type: 'button', class: 'tc-btn quiet', 'data-mode': 'words', 'aria-pressed': 'true', text: 'from words', onclick: pick('words') }),
    h('button', { type: 'button', class: 'tc-btn quiet', 'data-mode': 'photo', 'aria-pressed': 'false', text: 'from my photo', onclick: pick('photo') }));
  const make = h('button', { type: 'button', class: 'tc-btn', text: 'make my picture' });
  make.addEventListener('click', () => act(make, async () => {
    const description = words.querySelector('textarea').value.trim();
    const body = { mode, description: description || null };
    if (mode === 'photo') {
      if (!consent.checked) { toast('Tick "This is a photo of me" first.'); return; }
      const file = fileInput.files && fileInput.files[0];
      if (!file) { toast('Pick a photo of yourself first.'); return; }
      body.photo = await shrinkPhoto(file);
      body.photo_consent = true;
    } else if (!description) {
      toast("Describe how you'd like to look."); return;
    }
    fill(candidates, h('p', { class: 'muted-ink', text: 'making four pictures… this can take a minute' }));
    let out;
    try {
      out = await post('/api/portrait', body);
    } catch (e) {
      // say it where the person is looking, and keep it there (a toast is gone in 4 s)
      fill(candidates, h('p', { class: 'form-error', role: 'alert', text: errorText(e) }));
      throw e;
    }
    body.photo = null;
    fileInput.value = '';
    const colors = out.colors || [];
    fill(candidates, h('p', { text: 'pick one:' }), ...out.candidates.map((rows, i) => h('button', {
      type: 'button', class: 'candidate', 'aria-label': 'use this picture',
      onclick: (ev) => act(ev.currentTarget, async () => {
        const kept = await putPortrait(rows, mode, colors[i] || null);
        if (kept) { await refreshMe(); render(); }
      }) }, portraitPatch(rows, { small: true, colors: colors[i] || null }))));
  }));
  fill(card,
    state.me.portrait ? h('div', { class: 'row' }, h('button', { type: 'button', class: 'tc-textlink', text: 'remove my picture',
      onclick: (ev) => act(ev.currentTarget, async () => { await del('/api/portrait'); await refreshMe(); render(); }) })) : null,
    state.config.portraits_enabled ? modeRow : null,
    state.config.portraits_enabled ? words : null,
    state.config.portraits_enabled ? photo : null,
    state.config.portraits_enabled ? make : null,
    state.config.portraits_enabled ? null : h('p', { class: 'muted-ink', text: 'Pictures aren\'t set up on this server yet (it needs a MiniMax key). Until then your profile shows your initial.' }),
    candidates);
  return h('div', { class: 'stack', id: 'your-picture' }, phrase('your picture'), card);
}

function putPortrait(rows, source, colors) {
  return put('/api/portrait', { map: rows, source, colors });
}

meSections.push(pictureSection);

function profileForm() {
  const m = state.me;
  const field = (name, label, value, hint) => h('label', {}, h('span', { text: label }),
    h('input', { name, value: value || '', maxlength: name === 'location' || name === 'company' ? 60 : 160, placeholder: hint }));
  const form = h('form', { class: 'tc-card form' },
    field('location', 'based in', m.location, 'Belgrade'),
    field('company', 'company', m.company, 'Nebius Group'),
    field('expertise', 'expertise (up to 5, commas between)', (m.expertise || []).join(', '), 'AI adoption, Voice agents'),
    field('worth_knowing', 'worth knowing (up to 5, commas between)', (m.worth_knowing || []).join(', '), 'Speaks five languages, Made an AI film'),
    h('button', { type: 'submit', class: 'tc-btn', text: 'save your profile' }));
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const list = (k) => String(f.get(k) || '').split(',').map((x) => x.trim().slice(0, 30)).filter(Boolean).slice(0, 5);
    act(form.querySelector('[type=submit]'), async () => {
      state.me = await patch('/api/me', { location: String(f.get('location') || '').trim(), company: String(f.get('company') || '').trim(),
        expertise: list('expertise'), worth_knowing: list('worth_knowing') });
      toast('Saved.');
      render();
    });
  });
  return h('div', { class: 'stack' }, phrase('your profile'), form);
}

screens.me = async function me(root) {
  const m = state.me;
  const mine = await get(`/api/people/${encodeURIComponent(m.id)}`).catch(() => null);
  const toggle = (name, label) => {
    const box = h('input', { type: 'checkbox', checked: Boolean(m[name]) });
    box.addEventListener('change', () => act(box, async () => {
      state.me = await patch('/api/me', { [name]: box.checked });
    }).then(() => { box.checked = Boolean(state.me && state.me[name]); }));
    return h('label', { class: 'check' }, box, h('span', { text: label }));
  };
  fill(root,
    mine ? profileCard(mine, { isMe: true }) : title(firstName(m.name).toLowerCase() || 'me'),
    h('p', { class: 'counts', text: `${m.counts.followers} follower${m.counts.followers === 1 ? '' : 's'} · ${m.counts.following} following · ${m.counts.skills - m.counts.published} draft${m.counts.skills - m.counts.published === 1 ? '' : 's'}` }),
    h('nav', { class: 'profile-links', 'aria-label': 'yours' },
      h('a', { class: 'tc-btn on-ground', href: '#/skills', text: `your skills (${m.counts.skills})` }),
      h('a', { class: 'tc-btn on-ground quiet', href: '#/moments', text: 'your moments' }),
      h('a', { class: 'tc-btn on-ground quiet', href: '#/transcript', text: 'your transcript' }),
      h('a', { class: 'tc-btn on-ground quiet', href: '#/call', text: 'have a conversation' }),
      h('a', { class: 'tc-btn on-ground quiet', href: `#/people/${encodeURIComponent(m.id)}`, text: 'how others see you' })),
    profileForm(),
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
  if (wantPicture) {
    wantPicture = false;
    requestAnimationFrame(() => {
      const el = document.getElementById('your-picture');
      if (el) el.scrollIntoView({ block: 'start' });
    });
  }
};

// ---- router ----------------------------------------------------------------------------

export function parseRoute(hash) {
  const [path, query = ''] = String(hash || '').replace(/^#\/?/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const [name = '', id = null] = parts;
  const params = new URLSearchParams(query);
  if (name === 'people' && id) return { name: 'person', id: decodeURIComponent(id), params };
  return { name, id: null, params };
}

function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

// Which item of the shell (feed · network · profile · + connect) each screen belongs to.
const NAV_SECTION = { person: 'people', skills: 'me', moments: 'me', call: 'me', transcript: 'me', context: 'connect' };

async function render() {
  clearTimers();
  let route = parseRoute(location.hash);
  if (!screens[route.name]) route = { name: state.me ? 'feed' : 'start', id: null };
  if (!state.me && !PUBLIC_ROUTES.has(route.name)) route = { name: 'start', id: null };
  if (state.me && route.name === 'start') route = { name: 'feed', id: null };
  state.route = route;
  try { localStorage.setItem(LAST_ROUTE, `#/${route.name === 'person' ? `people/${route.id}` : route.name}`); } catch { /* private mode */ }
  for (const s of document.querySelectorAll('[data-screen]')) s.hidden = true;
  const key = route.name === 'person' ? 'person' : route.name;
  const root = document.querySelector(`[data-screen="${key}"]`);
  root.hidden = false;
  $('#nav').hidden = !state.me;
  $('#nav-top').hidden = !state.me;
  const section = NAV_SECTION[route.name] || route.name;
  for (const a of document.querySelectorAll('[data-nav]')) {
    if (a.dataset.nav === section) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  try {
    await screens[route.name](root, route.id, route.params);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { state.me = null; go('#/start'); return; }
    fill(root, title('hmm'), h('p', { class: 'lede', text: errorText(e) }));
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
  await pollBand();
  setInterval(pollBand, 5000); // the ListeningPill, on every screen
  render();
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', boot);
}

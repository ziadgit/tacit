// Tacit: the handshake test page. It connects the team's two bands in one Chrome tab,
// draws both motion traces, and shows the moment the two match: a handshake.
//
// Band numbers are never written in this file. They are typed on the page (or given in
// the address as ?a=NN&b=NN) and must be the team's own bands: TEAM_BANDS in
// src/tacit/config.py is the one place they live.
import { Band } from '../vexo-open-kit/js/src/index.js';
import { HandshakeDetector, DEFAULTS, describe } from './handshake-detector.js';

const $ = (selector) => document.querySelector(selector);
const say = (text) => { $('#message').textContent = text; };

const detector = new HandshakeDetector();
const bands = { a: null, b: null };

// ---------- connecting ----------

function numberOf(side) {
  const number = Number($(`#number-${side}`).value);
  return Number.isInteger(number) && number >= 1 && number <= 999 ? number : null;
}

async function connect(side) {
  const number = numberOf(side);
  const other = numberOf(side === 'a' ? 'b' : 'a');
  if (number === null) {
    return say("Type the band's number: it is written on the bag it came in. Only your own team's bands.");
  }
  if (number === other && bands[side === 'a' ? 'b' : 'a']) return say('That band is already connected on the other side.');
  const button = $(`#connect-${side}`);
  button.disabled = true;
  say(`Connecting to band ${number}: double-tap it (it blinks blue), then pick it in the list.`);
  try {
    const band = await Band.connect(number, { autoReconnect: true });
    bands[side] = band;
    $(`#name-${side}`).textContent = band.name;
    const feed = side === 'a' ? detector.feedA.bind(detector) : detector.feedB.bind(detector);
    // Both bands' clocks are set from this computer when they connect, so `time` is comparable.
    band.on('motion', (m) => feed(Number.isFinite(m.time) ? m.time : Date.now(), m.ax, m.ay, m.az));
    band.on('disconnect', () => {
      bands[side] = null;
      $(`#name-${side}`).textContent = 'not connected';
      button.disabled = false;
      say(`Band ${number} disconnected.`);
    });
    await band.configure({ motion: 50 });        // 50 samples a second is plenty for a handshake
    say(bands.a && bands.b ? 'Both bands connected. Shake hands.' : `Connected to ${band.name}. Now connect the other band.`);
  } catch (error) {
    button.disabled = false;
    say(error.message);                           // the kit's messages say what to do next
  }
  return undefined;
}

$('#connect-a').addEventListener('click', () => connect('a'));
$('#connect-b').addEventListener('click', () => connect('b'));

// ---------- drawing ----------

function draw(side, trace) {
  const canvas = $(`#trace-${side}`);
  const pen = canvas.getContext('2d');
  const { width, height } = canvas;
  pen.clearRect(0, 0, width, height);
  pen.strokeStyle = '#d8cfb8';
  pen.lineWidth = 1;
  pen.beginPath();
  pen.moveTo(0, height / 2);
  pen.lineTo(width, height / 2);
  pen.stroke();
  const latest = trace.latest;
  if (latest === null) return;
  const values = trace.resample(latest - 2000, latest, 20);
  if (!values) return;
  const { swing } = describe(values);
  pen.strokeStyle = side === 'a' ? '#2f5bff' : '#7a4fd6';
  pen.lineWidth = 3;
  pen.beginPath();
  swing.forEach((v, i) => {
    const x = (i / (swing.length - 1)) * width;
    const y = height / 2 - Math.max(-1.2, Math.min(1.2, v)) * (height / 2.6);
    if (i === 0) pen.moveTo(x, y); else pen.lineTo(x, y);
  });
  pen.stroke();
}

function celebrate(state) {
  const item = document.createElement('li');
  item.textContent = `${new Date().toLocaleTimeString()} · match ${state.match.toFixed(2)}`;
  $('#log').prepend(item);
  // Both wrists light up together. The light is free here because this page never turns the microphone on.
  for (const band of [bands.a, bands.b]) {
    if (!band) continue;
    band.setLed('#ffffff', { pattern: 'blink', period: 250 }).catch(() => {});
    setTimeout(() => band.ledOff().catch(() => {}), 1800);
  }
}

let greenUntil = 0;

function tick() {
  const state = detector.check();
  draw('a', detector.a);
  draw('b', detector.b);
  if (state.ready) {
    for (const side of ['a', 'b']) {
      $(`#energy-${side}`).textContent = state[side].energy.toFixed(2);
      $(`#swings-${side}`).textContent = state[side].swings;
      $(`#shaking-${side}`).dataset.on = String(state[side].shaking);
    }
    $('#match').textContent = state.match.toFixed(2);
    $('#lag').textContent = state.lagMs;
    $('#count').textContent = state.count;
    if (state.handshake) {
      greenUntil = Date.now() + 2200;
      celebrate(state);
    }
    const ring = $('#ring');
    if (Date.now() < greenUntil) {
      ring.dataset.state = 'yes';
      ring.textContent = 'handshake';
    } else if (state.a.shaking && state.b.shaking) {
      ring.dataset.state = 'near';
      ring.textContent = 'both shaking, not together';
    } else if (state.a.shaking || state.b.shaking) {
      ring.dataset.state = 'near';
      ring.textContent = 'one is shaking';
    } else {
      ring.dataset.state = 'idle';
      ring.textContent = 'no handshake';
    }
  }
  requestAnimationFrame(tick);
}

// ---------- tuning ----------

function slider(id, key) {
  const input = $(`#${id}`);
  const show = () => { $(`#${id}-out`).textContent = Number(input.value).toFixed(2); };
  input.value = DEFAULTS[key];
  show();
  input.addEventListener('input', () => {
    detector.options[key] = Number(input.value);
    show();
  });
}
slider('min-energy', 'minEnergy');
slider('min-match', 'minMatch');

// ---------- pretend motion, to check the logic without bands (add ?demo=1 to the address) ----------

function pretend(makeA, makeB, seconds = 1.6) {
  const start = Date.now();
  const timer = setInterval(() => {
    const now = Date.now();
    const t = (now - start) / 1000;
    const still = () => 1 + (Math.random() - 0.5) * 0.03;
    detector.feedA(now, 0, 0, t < seconds ? makeA(t) : still());
    detector.feedB(now, 0, 0, t < seconds ? makeB(t) : still());
    if (t > seconds + 2.5) clearInterval(timer);
  }, 20);
}
const wave = (hz, size, shift = 0) => (t) => 1 + size * Math.sin(2 * Math.PI * hz * t + shift) + (Math.random() - 0.5) * 0.06;
const quiet = () => 1 + (Math.random() - 0.5) * 0.03;
const wander = () => {
  let value = 0;
  return () => { value = value * 0.9 + (Math.random() - 0.5) * 0.25; return 1 + value; };
};

const address = new URLSearchParams(location.search);
if (address.has('demo')) {
  $('#demo').hidden = false;
  $('#sim-handshake').addEventListener('click', () => pretend(wave(3, 0.6), wave(3, 0.5, 0.25)));
  $('#sim-alone').addEventListener('click', () => pretend(wave(3, 0.6), quiet));
  $('#sim-apart').addEventListener('click', () => pretend(wave(3, 0.6), wave(4.3, 0.55, 1.7)));
  $('#sim-walk').addEventListener('click', () => pretend(wander(), wander(), 3));
}

// ---------- start ----------

for (const side of ['a', 'b']) {
  const given = Number(address.get(side));
  if (Number.isInteger(given) && given >= 1 && given <= 999) $(`#number-${side}`).value = given;
}
say("Type your band's number and your teammate's, connect both, then shake hands.");
requestAnimationFrame(tick);

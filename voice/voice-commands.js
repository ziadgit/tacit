// Tacit: the voice-command test page. It connects the team's band, turns the band's
// microphone into text (Deepgram), listens for "Vexo, open the feed" and the like, and
// switches the screen it shows. Two ways to give a command are compared:
//   1. the wake word: "Vexo, ..." at any time while the microphone is on;
//   2. double-tap the band, then say the command within a few seconds (no wake word).
// The band number comes from the address (?band=NN) and must be one of the team's own bands:
// TEAM_BANDS in src/tacit/config.py. No number is written in this file.
// The kit is loaded when the page opens, so the click on Connect goes straight to Bluetooth.
const kit = import('../vexo-open-kit/js/src/index.js').catch(() => null);

// The handshake: both wrists make the same motion at the same moment. The detector is the team's own
// (handshake-detector.js); this page only feeds it the motion of two bands and acts when it says yes.
const handshakeKit = import('../handshake/handshake-detector.js').catch(() => null);

const $ = (selector) => document.querySelector(selector);
const say = (text) => { $('#message').textContent = text; };

const ARM_SECONDS = 6;            // how long a double-tap waits for a command
const WAKE_WAIT_SECONDS = 5;      // how long after "Vexo" a command may follow
const DEEPGRAM = 'wss://api.deepgram.com/v1/listen?model=nova-3&language=en&encoding=opus&sample_rate=16000'
  + '&channels=1&interim_results=true&smart_format=true&endpointing=100&mip_opt_out=true&keyterm=Vexo&keyterm=Ziad';

// ---------- the screens (pictures of the designs stand in for the real app) ----------

const PHONE_SHOT = { aspect: '388 / 837', width: '281.44%', left: '-90.72%', top: '-4.78%' };   // the phone inside a 1092 x 1092 picture
const SCREENS = {
  // The feed is the real static page in screens/feed/; the others are pictures of the designs until their pages exist.
  feed: { title: 'Feed', page: '../screens/feed/index.html', aspect: '390 / 844' },
  profile: { title: 'My profile', src: 'shots/profile.png', ...PHONE_SHOT },
  network: { title: 'Network', src: 'shots/network.png', ...PHONE_SHOT },
  ziad: { title: 'Ziad · what he recommends', src: 'shots/person-ziad.png', ...PHONE_SHOT },
  connect: { title: 'Connect', src: 'shots/connect.png', aspect: '767 / 1100' },
};

// ---------- understanding a command (plain matching: instant, no model) ----------

// What the recogniser writes when it hears "Vexo". Add a word here when the test shows a new one.
const WAKE_WORDS = new Set(['vexo', 'vexos', 'vexa', 'vexor', 'vexel', 'vexxo', 'vexto', 'vecso', 'vekso', 'veksa',
  'vexoh', 'vexho', 'vexio', 'vexu', 'vexi', 'vex', 'vexed', 'vixo', 'vaxo', 'voxo', 'vesco', 'vezo', 'veso', 'vesso',
  'bexo', 'pexo', 'texo', 'lexo', 'wexo', 'dexo', 'rexo', 'nexo', 'flexo', 'plexo', 'texaco', 'mexico', 'vexel',
  'вексо', 'вэксо']);
const WAKE_FIRST = new Set(['vex', 'vec', 'vecs', 'vax', 'vek', 'bex', 'tex', 'lex', 'beck', 'vic']);
const WAKE_SECOND = new Set(['o', 'oh', 'so', 'ow', 'owe', 'all', 'or', 'ho']);
const NOT_WAKE = new Set(['veto', 'very', 'vest', 'vent', 'verb', 'vero', 'velo', 'expo', 'next', 'text', 'sexy']);

function oneLetterAway(word, target) {
  if (Math.abs(word.length - target.length) > 1) return false;
  let i = 0; let j = 0; let edits = 0;
  while (i < word.length && j < target.length) {
    if (word[i] === target[j]) { i += 1; j += 1; continue; }
    edits += 1;
    if (edits > 1) return false;
    if (word.length > target.length) i += 1;
    else if (word.length < target.length) j += 1;
    else { i += 1; j += 1; }
  }
  return edits + (word.length - i) + (target.length - j) <= 1;
}

/** How many words at `index` are the wake word: 0 (none), 1 ("vexo") or 2 ("vex oh"). */
function wakeAt(words, index) {
  const word = words[index];
  if (WAKE_FIRST.has(word) && WAKE_SECOND.has(words[index + 1])) return 2;
  if (WAKE_WORDS.has(word)) return 1;
  if (word.length >= 4 && !NOT_WAKE.has(word) && oneLetterAway(word, 'vexo')) return 1;
  return 0;
}

const tidy = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean);

const STOP = /\b(stop|quit|end|finish) (listening|listen|the mic|the microphone|recording|hearing)\b|\b(mic|microphone) off\b|\bgo to sleep\b|\bmute\b|^stop\b|перестань слушать|не слушай|выключи микрофон/;
const NOUNS = [
  ['feed', /(?<!\p{L})(feed|feeds|feet|feat|fede|fid|timeline|news|лент[ауые]|фид)(?!\p{L})/u],
  ['profile', /(?<!\p{L})(profile|profiles|profiled|pro file|my page|account|профиль)(?!\p{L})/u],
  ['network', /(?<!\p{L})(network|networks|net work|networking|contacts|my people|сеть|нетворк)(?!\p{L})/u],
];
const CONNECT = /(?<!\p{L})(connect|connects|connected|connecting|connection|handshake|kinect|коннект|соедини|познакомь)(?!\p{L})/u;
const BACK = /(?<!\p{L})(back|previous|return|назад|обратно)(?!\p{L})/u;
// A question about a person: "what did Ziad recommend me today?" opens his page. Names are often misheard.
const ZIAD = /(?<!\p{L})(ziad|ziyad|zyad|zeyad|ziad's|ziads|zied|zead|zayed|zaid|zad|zeod|zion|siad|the odd|z add|зияд|зиад)(?!\p{L})/u;
const ASKING = /(?<!\p{L})(recommend|recommends|recommended|recommendation|recommendations|advice|advise|advised|suggest|suggested|suggests|tips?|skills?|say|said|told|share|shared|советовал|посоветовал|рекомендовал|рекомендует)(?!\p{L})/u;
const VERB = /\b(open|show|go to|take me|switch to|bring up|pull up|go back|stop listening|connect|открой|покажи)\b/u;

/** Which command a list of words means: { id, index } (index = the word that decided it) or null. */
function parseCommand(words) {
  const text = words.join(' ');
  const wordAt = (position) => text.slice(0, position).split(' ').length - 1;
  const stop = STOP.exec(text);
  if (stop) return { id: 'stop', index: wordAt(stop.index + stop[0].length - 1) };
  const person = ZIAD.exec(text);
  if (person) return { id: 'ziad', index: wordAt(person.index + person[0].length - 1) };
  let best = null;
  for (const [id, pattern] of NOUNS) {
    const found = pattern.exec(text);
    if (found && (!best || found.index < best.at)) best = { id, at: found.index, end: found.index + found[0].length - 1 };
  }
  if (best) return { id: best.id, index: wordAt(best.end) };
  const connect = CONNECT.exec(text);
  if (connect) return { id: 'connect', index: wordAt(connect.index) };
  const back = BACK.exec(text);
  if (back) return { id: 'back', index: wordAt(back.index) };
  return null;
}

/** A typed or finished sentence: is there a wake word, and which command follows it? */
function understand(text) {
  const words = tidy(text);
  const whole = words.join(' ');
  if (ZIAD.test(whole) && ASKING.test(whole)) return { wake: false, command: 'ziad', question: true };
  for (let i = 0; i < words.length; i += 1) {
    const length = wakeAt(words, i);
    if (!length) continue;
    const command = parseCommand(words.slice(i + length, i + length + 10));
    return { wake: true, command: command ? command.id : null };
  }
  const command = parseCommand(words);
  return { wake: false, command: command ? command.id : null };
}

// ---------- state ----------

const state = {
  bandNumber: null,       // the band of this laptop, from ?band=NN in the address
  band: null,
  other: null,            // the second band, for the handshake
  detector: null,
  ears: null,             // the Deepgram connection
  earsKey: '',            // lives in this variable only: never stored, never in the address
  micOn: false,
  sentSeconds: 0,         // seconds of sound sent on this Deepgram connection (20 ms a packet)
  finalWords: [],         // { w, start, end } settled words, in the connection's own time
  interimWords: [],       // the current guess
  consumedUntil: 0,       // words before this moment were already used
  armed: null,            // { from, until, deadline, timer } after a double-tap
  holdTimer: null,
  wakeHint: 0,            // end time of a "Vexo" that still waits for its command
  current: null,          // the screen on show
  history: [],
  log: [],
  lastFire: { id: null, at: 0 },
};

function element(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;            // text from speech: never as HTML
  return made;
}

function pill(id, on, text) {
  const item = $(id);
  item.dataset.on = String(on);
  if (text) item.textContent = text;
}

// ---------- showing a screen ----------

function show(id) {
  const frame = $('#frame');
  const image = $('#shot');
  state.current = id;
  if (!id) {
    frame.hidden = true;
    $('#idle').hidden = false;
    $('#screen-name').textContent = 'No screen open';
    return;
  }
  const screen = SCREENS[id];
  $('#idle').hidden = true;
  frame.hidden = false;
  frame.style.aspectRatio = screen.aspect;
  const page = $('#page');
  page.hidden = !screen.page;
  image.hidden = Boolean(screen.page);
  if (screen.page && page.getAttribute('src') !== screen.page) page.src = screen.page;
  image.style.width = screen.width || '100%';
  image.style.left = screen.left || '0';
  image.style.top = screen.top || '0';
  if (screen.src) image.src = screen.src;
  image.alt = `${screen.title} (a picture of the design)`;
  $('#screen-name').textContent = screen.title;
  frame.classList.remove('pop');
  void frame.offsetWidth;                                     // restart the little animation
  frame.classList.add('pop');
}

function beep() {
  if (!$('#sound').checked) return;
  try {
    const sound = beep.context || (beep.context = new AudioContext());
    const tone = sound.createOscillator();
    const volume = sound.createGain();
    tone.frequency.value = 880;
    volume.gain.setValueAtTime(0.12, sound.currentTime);
    volume.gain.exponentialRampToValueAtTime(0.001, sound.currentTime + 0.18);
    tone.connect(volume).connect(sound.destination);
    tone.start();
    tone.stop(sound.currentTime + 0.2);
  } catch { /* no sound is fine */ }
}

// ---------- the log (this is what the test counts) ----------

const WAYS = { wake: 'wake word', tap: 'double-tap', typed: 'typed', handshake: 'handshake', question: 'question, no wake word' };

function record(entry) {
  entry.n = state.log.length + 1;
  entry.time = new Date().toLocaleTimeString();
  state.log.push(entry);
  const row = element('tr', entry.kind);
  row.append(
    element('td', '', String(entry.n)),
    element('td', '', entry.time),
    element('td', '', entry.kind === 'done' ? WAYS[entry.way] : entry.kind === 'no-wake' ? 'no “Vexo”' : entry.kind === 'no-command' ? '“Vexo” only' : 'double-tap'),
    element('td', 'heard', `“${entry.heard}”`),
    element('td', '', entry.did),
    element('td', '', Number.isFinite(entry.delay) ? `${entry.delay.toFixed(1)} s` : ''),
  );
  $('#log').prepend(row);
  showCounts();
}

function showCounts() {
  const count = (test) => state.log.filter(test).length;
  const delays = state.log.filter((e) => e.kind === 'done' && Number.isFinite(e.delay)).map((e) => e.delay);
  const average = delays.length ? (delays.reduce((a, b) => a + b, 0) / delays.length).toFixed(1) : '-';
  $('#counts').textContent = [
    `wake word: ${count((e) => e.kind === 'done' && e.way === 'wake')}`,
    `double-tap: ${count((e) => e.kind === 'done' && e.way === 'tap')}`,
    `handshakes: ${count((e) => e.kind === 'done' && e.way === 'handshake')}`,
    `typed: ${count((e) => e.kind === 'done' && e.way === 'typed')}`,
    `“Vexo” but no command: ${count((e) => e.kind === 'no-command')}`,
    `command but no “Vexo”: ${count((e) => e.kind === 'no-wake')}`,
    `double-tap, nothing understood: ${count((e) => e.kind === 'tap-miss')}`,
    `average wait: ${average} s`,
  ].join(' · ');
}

function logAsText() {
  const lines = state.log.map((e) => [e.n, e.time, e.kind, e.way || '', e.command || '', Number.isFinite(e.delay) ? e.delay.toFixed(2) : '', `"${e.heard}"`].join('\t'));
  return [$('#counts').textContent, 'n\ttime\tkind\tway\tcommand\twait_s\theard', ...lines].join('\n');
}

// ---------- doing a command ----------

function act(command, way, heard, delay) {
  const now = Date.now();
  if (command === state.lastFire.id && now - state.lastFire.at < 1500) return;      // the same sentence, heard twice
  state.lastFire = { id: command, at: now };
  let did;
  if (command === 'stop') {
    did = 'Microphone off';
    micOff();
  } else if (command === 'back') {
    if (state.history.length) {
      show(state.history.pop());
      did = state.current ? `Back to ${SCREENS[state.current].title}` : 'Back to the start';
    } else {
      did = 'Nothing to go back to';
    }
  } else {
    if (state.current !== command) state.history.push(state.current);
    show(command);
    did = `Opened ${SCREENS[command].title}`;
  }
  beep();
  $('#last-heard').textContent = `“${heard}”`;
  $('#last-did').textContent = did;
  $('#last-how').textContent = `${WAYS[way]}${Number.isFinite(delay) ? ` · ${delay.toFixed(1)} s after the last word` : ''}`;
  $('#last').dataset.fresh = 'true';
  setTimeout(() => { $('#last').dataset.fresh = 'false'; }, 1200);
  record({ kind: 'done', way, command, heard, did, delay });
}

// ---------- listening: words with their times ----------

const phrase = (words) => words.map((word) => word.show).join(' ');

function evaluate(force = false) {
  clearTimeout(state.holdTimer);
  const words = state.finalWords.concat(state.interimWords).filter((word) => word.start >= state.consumedUntil - 0.001);
  const plain = words.map((word) => word.w);
  const settledUntil = state.finalWords.length ? state.finalWords[state.finalWords.length - 1].end : 0;

  const fire = (command, way, from, list) => {
    const decided = list[command.index];
    // "go back" may still become "go back to the feed": wait for the sentence to settle.
    if (command.id === 'back' && !force && decided.end > settledUntil && command.index >= list.length - 2) {
      state.holdTimer = setTimeout(() => evaluate(true), 700);
      return true;
    }
    state.consumedUntil = decided.end;
    state.wakeHint = 0;
    const delay = Math.max(0, state.sentSeconds - decided.end);
    act(command.id, way, phrase(words.slice(Math.max(0, from), words.indexOf(decided) + 1)), delay);
    return true;
  };

  // 1. after a double-tap: any command, no wake word needed
  if (state.armed) {
    const list = words.filter((word) => word.start >= state.armed.from - 0.2 && word.start <= state.armed.until);
    const command = parseCommand(list.map((word) => word.w));
    if (command) {
      if (fire(command, 'tap', words.indexOf(list[0]), list)) { if (state.consumedUntil >= list[command.index].end) disarm(); }
      return;
    }
  }

  // 2. the wake word, then a command
  for (let i = 0; i < plain.length; i += 1) {
    const length = wakeAt(plain, i);
    if (!length) continue;
    const wakeEnd = words[i + length - 1].end;
    const list = words.slice(i + length).filter((word) => word.start - wakeEnd <= WAKE_WAIT_SECONDS).slice(0, 10);
    const command = parseCommand(list.map((word) => word.w));
    if (command) {
      fire(command, 'wake', i, list);
      return;
    }
    if (state.sentSeconds - wakeEnd > WAKE_WAIT_SECONDS) {       // "Vexo" and then nothing we know
      state.consumedUntil = list.length ? list[list.length - 1].end : wakeEnd;
      state.wakeHint = 0;
      record({ kind: 'no-command', heard: phrase(words.slice(i, i + length + list.length)), did: 'Nothing: no command understood after “Vexo”' });
      $('#hint').textContent = '';
      return;
    }
    state.wakeHint = wakeEnd;
    $('#hint').textContent = 'Heard “Vexo”… say the command.';
    return;
  }
  // 3. a question about Ziad needs no wake word: the name plus "recommend" is rare enough in other talk
  const text = plain.join(' ');
  if (ZIAD.test(text) && ASKING.test(text)) {
    const command = parseCommand(plain);
    if (command && command.id === 'ziad' && (force || words[words.length - 1].end <= settledUntil)) {
      state.consumedUntil = words[words.length - 1].end;
      act('ziad', 'question', phrase(words), Math.max(0, state.sentSeconds - words[words.length - 1].end));
      return;
    }
  }
  if (!state.armed) $('#hint').textContent = '';
}

function onResults(answer) {
  const best = answer.channel?.alternatives?.[0];
  if (!best) return;
  const words = (best.words || []).map((word) => ({
    w: tidy(word.word || '')[0] || '', show: word.punctuated_word || word.word, start: word.start, end: word.end,
  })).filter((word) => word.w);
  if (answer.is_final) {
    state.interimWords = [];
    state.finalWords.push(...words);
    const oldest = state.sentSeconds - 15;
    state.finalWords = state.finalWords.filter((word) => word.end >= oldest);
    $('#interim').textContent = '';
    if (best.transcript) {
      const lines = $('#heard');
      lines.append(element('li', '', best.transcript));
      while (lines.children.length > 6) lines.firstChild.remove();
      $('#heard-empty').hidden = true;
    }
  } else {
    state.interimWords = words;
    $('#interim').textContent = best.transcript || '';
  }
  const before = state.log.length;
  evaluate();
  // A finished sentence that sounds like a command but had no "Vexo" in front: note it, do nothing.
  if (answer.is_final && state.log.length === before && !state.armed && !state.wakeHint && words.length
      && words[0].start >= state.consumedUntil) {
    const text = words.map((word) => word.w).join(' ');
    if (VERB.test(text) && parseCommand(words.map((word) => word.w))) {
      record({ kind: 'no-wake', heard: best.transcript, did: 'Nothing: sounded like a command, but no “Vexo” was heard' });
    }
  }
}

function openEars() {
  if (!state.earsKey || state.ears) return;
  const ears = new WebSocket(DEEPGRAM, ['token', state.earsKey]);      // the key rides in the protocol field
  state.ears = ears;
  state.sentSeconds = 0;
  state.finalWords = [];
  state.interimWords = [];
  state.consumedUntil = 0;
  let alive = null;
  ears.onopen = () => {
    pill('#st-ears', true);
    alive = setInterval(() => ears.readyState === 1 && ears.send(JSON.stringify({ type: 'KeepAlive' })), 4000);
  };
  ears.onmessage = (event) => {
    const answer = JSON.parse(event.data);
    if (answer.type === 'Results') onResults(answer);
  };
  ears.onclose = () => {
    clearInterval(alive);
    if (state.ears === ears) state.ears = null;
    pill('#st-ears', false);
    $('#interim').textContent = '';
  };
  ears.onerror = () => say('Deepgram refused the connection. The usual reasons: a wrong key, no credit, no internet.');
}

function closeEars() {
  const ears = state.ears;
  state.ears = null;
  if (!ears) return;
  try { if (ears.readyState === 1) ears.send(JSON.stringify({ type: 'CloseStream' })); } catch { /* closing anyway */ }
  setTimeout(() => ears.close(), 300);
}

// ---------- the microphone ----------

function showMic() {
  pill('#st-mic', state.micOn, state.micOn ? 'Microphone on' : 'Microphone off');
  $('#deepgram-note').hidden = !state.micOn;
  $('#mic').textContent = state.micOn ? 'Turn microphone off' : 'Turn microphone on';
  $('#mic').disabled = !state.band;
  document.body.dataset.mic = String(state.micOn);
}

async function micOn() {
  if (!state.band) return say('Connect the band first.');
  if (!state.earsKey) {
    const typed = $('#dg-key').value.trim();
    if (!typed) return say('Type the team’s Deepgram key into the key field first. Without it nothing is sent and there is no text.');
    keepKey(typed);
  }
  try {
    openEars();
    await state.band.configure({ audio: true });               // the light goes solid blue: the microphone is on
    state.micOn = true;
    showMic();
    say('The microphone is on. Say: “Vexo, open the feed”. Or double-tap the band and say “open the feed”.');
  } catch (error) {
    say(error.message);
  }
  return undefined;
}

async function micOff() {
  disarm();
  closeEars();
  state.micOn = false;
  showMic();
  try {
    if (state.band) await state.band.configure({ audio: false });
    say('The microphone is off; nothing is sent. Double-tap the band, or press the button, to turn it on again.');
  } catch (error) {
    say(error.message);
  }
}

function keepKey(value) {
  state.earsKey = value;
  $('#dg-key').value = '';
  $('#dg-key').placeholder = value ? 'Deepgram key is in this page’s memory (reload forgets it)' : 'Deepgram key';
  $('#forget').hidden = !value;
}

// ---------- double-tap: "now I will say a command" ----------

function disarm() {
  if (!state.armed) return;
  clearTimeout(state.armed.timer);
  state.armed = null;
  $('#armed').hidden = true;
  $('#hint').textContent = '';
}

function arm() {
  disarm();
  const from = state.sentSeconds;
  state.armed = {
    from,
    until: from + ARM_SECONDS,
    timer: setTimeout(() => {
      const armed = state.armed;
      if (!armed) return;
      const heard = state.finalWords.concat(state.interimWords).filter((word) => word.start >= armed.from - 0.2);
      disarm();
      record({ kind: 'tap-miss', heard: phrase(heard), did: 'Nothing: no command understood after the double-tap' });
    }, (ARM_SECONDS + 2) * 1000),                               // the words of the last second arrive a little later
  };
  state.consumedUntil = Math.max(state.consumedUntil, from - 0.2);
  $('#armed').hidden = false;
  $('#hint').textContent = 'Double-tap felt. Say the command now (no “Vexo” needed).';
  const bar = $('#armed-bar');
  bar.style.transition = 'none';
  bar.style.transform = 'scaleX(1)';
  requestAnimationFrame(() => {
    bar.style.transition = `transform ${ARM_SECONDS}s linear`;
    bar.style.transform = 'scaleX(0)';
  });
}

async function doubleTap() {
  if (!state.micOn) {
    await micOn();
    if (!state.micOn) return;
  }
  arm();
}

// ---------- the band ----------

async function connect() {
  if (!state.bandNumber) return say('Add your own band number to the address, for example voice/?band=NN (your TACIT_BAND).');
  $('#connect').disabled = true;
  say(`Connecting to band ${state.bandNumber}: double-tap it (it blinks blue), then pick it in the list.`);
  try {
    const loaded = await kit;
    if (!loaded) throw new Error('The Vexo kit is not in this folder. Run scripts/bootstrap.sh, serve the repository folder, and reload.');
    const { Band } = loaded;
    const band = await Band.connect(state.bandNumber, { autoReconnect: true });
    state.band = band;
    band.on('double-tap', doubleTap);
    band.on('audio', (packet) => {
      if (state.ears?.readyState !== 1) return;
      state.ears.send(packet.opus);                             // one Opus packet = one binary message
      state.sentSeconds += 0.02;
    });
    band.on('motion', (m) => state.detector?.feedA(Number.isFinite(m.time) ? m.time : Date.now(), m.ax, m.ay, m.az));
    band.on('reconnecting', () => { pill('#st-band', false); say('The link dropped. Trying to get it back…'); });
    band.on('reconnected', () => { pill('#st-band', true); say(`Back with ${band.name}.`); });
    band.on('disconnect', () => {
      state.band = null;
      state.micOn = false;
      closeEars();
      disarm();
      pill('#st-band', false, 'Band');
      showMic();
      $('#connect').disabled = false;
      say('Disconnected.');
    });
    band.on('stream-taken', (event) => say(event.message));
    await band.configure({ events: true, motion: 50 });        // motion is for the handshake
    pill('#st-band', true, band.name);
    showMic();
    say(`Connected to ${band.name}. Next: the Deepgram key, then “Turn microphone on”.`);
  } catch (error) {
    $('#connect').disabled = false;
    say(error.message);                                         // the kit's messages say what to do next
  }
  return undefined;
}

// ---------- the handshake (two bands in this one tab) ----------

async function connectOther() {
  const number = Number($('#other-number').value);
  if (!Number.isInteger(number) || number < 1 || number > 999) {
    return say("Type the other band's number: it is written on its bag. It must be your own teammate's band.");
  }
  if (number === state.bandNumber) return say('That is your own band. Type your teammate\u2019s number.');
  if (!state.detector) return say('The handshake detector is not in this folder (handshake-detector.js).');
  $('#connect-other').disabled = true;
  say(`Connecting to band ${number}: double-tap it (it blinks blue), then pick it in the list.`);
  try {
    const loaded = await kit;
    if (!loaded) throw new Error('The Vexo kit is not in this folder.');
    const band = await loaded.Band.connect(number, { autoReconnect: true });
    state.other = band;
    // Both bands' clocks are set from this computer when they connect, so `time` is comparable.
    band.on('motion', (m) => state.detector?.feedB(Number.isFinite(m.time) ? m.time : Date.now(), m.ax, m.ay, m.az));
    band.on('disconnect', () => {
      state.other = null;
      pill('#st-other', false, 'Other band');
      $('#connect-other').disabled = false;
      say(`Band ${number} disconnected.`);
    });
    await band.configure({ motion: 50 });
    pill('#st-other', true, band.name);
    say(`Connected to ${band.name}. Shake hands: when both wrists move together, the two of you are connected.`);
  } catch (error) {
    $('#connect-other').disabled = false;
    say(error.message);
  }
  return undefined;
}

function onHandshake(found) {
  if (state.current !== 'network') state.history.push(state.current);
  show('network');                                            // the person you just met is at the top of the network
  beep();
  const did = 'Connected: opened Network';
  $('#last-heard').textContent = 'Handshake felt on both bands';
  $('#last-did').textContent = did;
  $('#last-how').textContent = `handshake · the two motions match ${found.match.toFixed(2)}`;
  $('#last').dataset.fresh = 'true';
  setTimeout(() => { $('#last').dataset.fresh = 'false'; }, 1200);
  record({ kind: 'done', way: 'handshake', command: 'handshake', heard: `two bands shook together (match ${found.match.toFixed(2)})`, did });
}

setInterval(() => {
  if (!state.detector) return;
  const found = state.detector.check();
  if (found.handshake) onHandshake(found);
}, 40);

// Pretend motion on both sides, to check the logic with no bands: voice.pretendHandshake(true) is a
// handshake, voice.pretendHandshake(false) is one person shaking alone.
function pretendHandshake(together = true) {
  const start = Date.now();
  const timer = setInterval(() => {
    const now = Date.now();
    const t = (now - start) / 1000;
    const still = () => 1 + (Math.random() - 0.5) * 0.03;
    const wave = (shift) => 1 + 0.6 * Math.sin(2 * Math.PI * 3 * t + shift) + (Math.random() - 0.5) * 0.06;
    state.detector?.feedA(now, 0, 0, t < 1.6 ? wave(0) : still());
    state.detector?.feedB(now, 0, 0, t < 1.6 && together ? wave(0.25) : still());
    if (t > 4) clearInterval(timer);
  }, 20);
}

handshakeKit.then((loaded) => {
  if (!loaded) return;
  state.detector = new loaded.HandshakeDetector();
  $('#connect-other').disabled = false;
});

// ---------- wiring ----------

$('#connect-other').addEventListener('click', connectOther);

$('#connect').addEventListener('click', connect);
$('#mic').addEventListener('click', () => (state.micOn ? micOff() : micOn()));
$('#dg-key').addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  keepKey(event.target.value.trim());
  say(state.earsKey ? 'Deepgram key kept in this page only. Now turn the microphone on.' : 'No key typed.');
});
$('#forget').addEventListener('click', () => {
  if (state.micOn) micOff();
  keepKey('');
  say('Key forgotten.');
});

function typed(text) {
  const clean = text.trim();
  if (!clean) return;
  const found = understand(clean);
  if (found.command && (found.wake || found.question)) {
    act(found.command, 'typed', clean);
  } else {
    $('#last-heard').textContent = `“${clean}”`;
    $('#last-did').textContent = found.wake ? 'Heard “Vexo”, but no command after it' : 'Not a command';
    $('#last-how').textContent = 'typed';
  }
}
$('#typed').addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  typed(event.target.value);
  event.target.value = '';
});
for (const button of document.querySelectorAll('[data-say]')) {
  button.addEventListener('click', () => typed(button.dataset.say));
}
$('#copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(logAsText());
    say('The log is copied. Paste it into the chat.');
  } catch {
    say('Could not copy. Select the table by hand.');
  }
});
$('#clear').addEventListener('click', () => {
  state.log = [];
  $('#log').replaceChildren();
  showCounts();
});

setInterval(() => { if (state.micOn && (state.wakeHint || state.armed)) evaluate(); }, 1000);

// For checking the logic from the console, and for reading the log.
window.voice = { pretendHandshake, understand, parseCommand, tidy, typed, state, logAsText };

const asked = Number(new URLSearchParams(location.search).get('band'));
state.bandNumber = Number.isInteger(asked) && asked >= 1 && asked <= 999 ? asked : null;
$('#connect').textContent = state.bandNumber ? `Connect band ${state.bandNumber}` : 'Connect';
say(state.bandNumber
  ? `Your band is ${state.bandNumber}. Close any other tab that holds the band, then press Connect. Or try a command in the box below.`
  : 'No band number yet: add ?band=NN (your own TACIT_BAND) to the address. The typed commands below work without a band.');
const other = Number(new URLSearchParams(location.search).get('other'));
if (Number.isInteger(other) && other >= 1 && other <= 999) $('#other-number').value = String(other);
show(null);
showMic();
showCounts();

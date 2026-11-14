// Checks the handshake logic on made-up motion. Run:  node --test handshake/
// These are artificial waves, not real wrists: they show the logic holds together,
// not that the thresholds are right for people.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HandshakeDetector } from './handshake-detector.js';

// A small repeatable noise source, so the test gives the same answer every run.
function noise(seed) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296 - 0.5;
  };
}

/** Feed both bands for `seconds` of motion and say how many handshakes were recognised. */
function run(makeA, makeB, seconds = 1.6) {
  const detector = new HandshakeDetector();
  const jitterA = noise(1);
  const jitterB = noise(2);
  let handshakes = 0;
  for (let ms = 0; ms <= (seconds + 2.5) * 1000; ms += 20) {
    const t = ms / 1000;
    const still = (jitter) => 1 + jitter() * 0.03;
    detector.feedA(ms, 0, 0, t < seconds ? makeA(t, jitterA) : still(jitterA));
    detector.feedB(ms, 0, 0, t < seconds ? makeB(t, jitterB) : still(jitterB));
    if (detector.check().handshake) handshakes += 1;
  }
  return handshakes;
}

const wave = (hz, size, shift = 0) => (t, jitter) => 1 + size * Math.sin(2 * Math.PI * hz * t + shift) + jitter() * 0.06;
const quiet = (t, jitter) => 1 + jitter() * 0.03;
const wander = () => {
  let value = 0;
  return (t, jitter) => { value = value * 0.9 + jitter() * 0.25; return 1 + value; };
};

test('two wrists moving together are one handshake', () => {
  assert.equal(run(wave(3, 0.6), wave(3, 0.5, 0.25)), 1);
});

test('one person shaking alone is not a handshake', () => {
  assert.equal(run(wave(3, 0.6), quiet), 0);
});

test('two people shaking at different rhythms is not a handshake', () => {
  assert.equal(run(wave(3, 0.6), wave(4.3, 0.55, 1.7)), 0);
});

test('both people just moving around is not a handshake', () => {
  assert.equal(run(wander(), wander(), 3), 0);
});

test('a second handshake right after the first is not counted twice', () => {
  assert.equal(run(wave(3, 0.6), wave(3, 0.6), 2.4), 1);
});

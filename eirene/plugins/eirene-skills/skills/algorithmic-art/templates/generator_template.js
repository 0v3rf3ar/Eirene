/*
 * p5.js generative art — structure and good practice.
 *
 * This file shows how to organise a sketch. It does not tell you what to make:
 * your algorithmic philosophy decides that. Put your final code inline in the
 * viewer HTML rather than shipping this file.
 */

// 1. Parameters ---------------------------------------------------------------
// Everything tunable lives in one object, so the UI can bind to it, Reset can
// restore it, and a configuration can be saved or shared as JSON.
const DEFAULTS = {
  seed: 12345,
  palette: ["#1f3a5f", "#e0a458", "#c8553d", "#f2efe9"], // choose your own
  // counts: how many elements (particles, cells, branches…)
  // scales: size, speed, spacing
  // probabilities: how likely an event is
  // angles: rotation, direction
};
let params = structuredClone(DEFAULTS);

// 2. Seeded randomness ---------------------------------------------------------
// Seed both generators before generating anything. After this, random() and
// noise() are deterministic. Never use Math.random() in the artwork.
function seedEverything(seed) {
  randomSeed(seed);
  noiseSeed(seed);
}

// 3. Lifecycle -------------------------------------------------------------------
// Three common shapes:
//  a) static: build and draw in setup(), call noLoop();
//  b) animated: update the system every frame in draw(), optionally stop after N frames;
//  c) on demand: noLoop() by default and call redraw() when a parameter changes.
let system = [];

function setup() {
  const canvas = createCanvas(1200, 1200);
  canvas.parent("canvas-container");
  pixelDensity(1); // predictable export size; raise for retina exports
  build();
}

function build() {
  seedEverything(params.seed);
  system = [];
  // create the elements of your system here, using random() and noise()
}

function draw() {
  // update and render
}

// 4. Classes for entities -----------------------------------------------------
// Keep state, update and rendering separate.
class Agent {
  constructor(x, y) {
    this.pos = createVector(x, y);
    this.vel = p5.Vector.random2D(); // seeded
  }
  update() {
    // physics, rules, neighbours
  }
  show() {
    // drawing only
  }
}

// 5. Performance ---------------------------------------------------------------
// - Precompute what does not change (fields, lookup tables).
// - For neighbour queries use a grid or spatial hash, not all-pairs loops.
// - Avoid sqrt/trig in hot loops when a squared distance or table will do.
// - Draw many points with beginShape(POINTS) or directly into pixels[].
// - For long accumulations, draw into a createGraphics() buffer once.

// 6. Utilities ------------------------------------------------------------------
function pick(list) {
  return list[floor(random(list.length))];
}

function paletteColor(index, alpha = 255) {
  const c = color(params.palette[index % params.palette.length]);
  c.setAlpha(alpha);
  return c;
}

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - pow(-2 * t + 2, 3) / 2;
}

function wrap(value, max) {
  return ((value % max) + max) % max;
}

function fieldAngle(x, y, scale, octaves = 1) {
  let total = 0, amp = 1, freq = scale, norm = 0;
  for (let i = 0; i < octaves; i++) {
    total += noise(x * freq, y * freq) * amp;
    norm += amp;
    amp *= 0.5;
    freq *= 2;
  }
  return (total / norm) * TWO_PI * 2;
}

// Fade the canvas towards the background for trails.
function fade(hex, alpha) {
  const c = color(hex);
  c.setAlpha(alpha);
  noStroke();
  fill(c);
  rect(0, 0, width, height);
}

// 7. Parameter changes ------------------------------------------------------------
// Some parameters can apply live (a color); others need build() again (a count).
function setParam(name, value, rebuild = true) {
  params[name] = value;
  if (rebuild) build();
  redraw();
}

// 8. Export ---------------------------------------------------------------------
function exportPNG() {
  saveCanvas(`artwork-seed-${params.seed}`, "png");
}

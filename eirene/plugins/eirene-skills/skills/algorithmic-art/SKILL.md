---
name: algorithmic-art
description: Create original generative art in p5.js with seeded randomness and live parameter controls, delivered as one self-contained HTML viewer. Use when someone asks for art made with code — generative or algorithmic art, flow fields, particle systems, noise studies. Always original; never copy an existing artist's work.
---

# Algorithmic art

An algorithmic philosophy is a computational aesthetic movement, expressed in
code. You deliver a `.md` file (the philosophy) and a single `.html` file (an
interactive viewer with the algorithm inside).

Two steps:

1. **Write the algorithmic philosophy** (`.md`).
2. **Express it as p5.js generative art** in one HTML file built from
   `templates/viewer.html`.

## Step 1 — the algorithmic philosophy

Write a philosophy — not a static picture, not a template — that will be carried
out through:

- computational processes, emergent behaviour, mathematical beauty;
- seeded randomness, noise fields, organic systems;
- particles, flows, fields and forces;
- parametric variation and controlled chaos.

### What this step is

- **What you were given:** the person's request, perhaps a slight one. Use it as
  a foundation, not a constraint.
- **What you write:** the manifesto of a generative art movement.
- **What happens next:** you express that manifesto in code — sketches that are
  about 90% algorithmic generation and 10% essential parameters.

The philosophy puts the algorithm first: emergent behaviour, computational
beauty, seeded variation.

### Writing it

**Name the movement** in one or two words: "Organic Turbulence", "Quantum
Harmonics", "Emergent Stillness".

**Describe it in 4–6 paragraphs**, concise but complete, covering how it lives
in:

- computational processes and mathematical relationships;
- noise and patterns of randomness;
- particle behaviour and field dynamics;
- change over time and system state;
- parametric variation and emergent complexity.

Rules:

- **No repetition.** Each aspect once; return to noise, particles or mathematics
  only to go deeper.
- **Insist on craft, more than once.** Say repeatedly that the final algorithm
  should feel as though it took countless hours to develop, was refined with
  care, and comes from someone at the very top of the field — "a meticulously
  crafted algorithm", "the product of deep computational expertise", "painstaking
  tuning", "master-level implementation".
- **Leave room.** Be specific about direction, but brief enough that the
  implementation still has real choices to make, at the same level of craft.

Beauty lives in the process, not the final frame; the philosophy must lead to an
algorithm, not a static image.

### Short examples

Compressed; yours should be 4–6 full paragraphs.

**Organic Turbulence** — chaos held by natural law; order out of disorder. Flow
fields from layered Perlin noise. Thousands of particles follow the vectors and
their trails pile up into organic density maps. Several noise octaves make
turbulent regions and calm ones. Color comes from speed and density: fast
particles burn bright, slow ones sink into shadow. It runs until it settles — a
balance tuned over countless iterations by a master of computational aesthetics.

**Quantum Harmonics** — discrete things behaving like waves. Particles on a grid,
each with a phase that turns through sine waves. Where they are close, phases
interfere: constructive interference makes bright nodes, destructive makes
voids. Simple harmonic motion grows into complex mandalas. The result of
painstaking frequency calibration, every ratio chosen to resonate.

**Recursive Whispers** — the same shape at every scale; infinite depth in a
finite space. Branching structures that subdivide recursively, each branch a
little random but held to golden ratios. L-systems or recursive subdivision make
forms both mathematical and organic. Slight noise breaks perfect symmetry. Lines
thin with each level. Every branching angle the result of deep mathematical
exploration.

**Field Dynamics** — invisible forces made visible by what they move. Vector
fields from functions or noise. Particles are born at the edges, follow field
lines, and die at equilibrium or the boundary. Fields attract, repel, rotate.
Only the traces remain — ghostly evidence of forces you cannot see. A dance
choreographed through careful balance of forces.

**Stochastic Crystallization** — random processes settling into order. Circle
packing or Voronoi tessellation from random points, relaxed until cells stop
pushing. Color from cell size, neighbour count or distance from the centre. The
tiling feels both random and inevitable. Every seed gives a new crystal — the
mark of a master-level generative algorithm.

### Principles

- **Algorithmic philosophy:** a computational worldview to express in code.
- **Process over product:** the beauty is in running the algorithm; every seed
  is different.
- **Parametric expression:** ideas carried by relationships, forces and
  behaviours, not a fixed composition.
- **Artistic freedom:** leave the implementation room to interpret.
- **Living algorithms:** not static images with a bit of randomness.
- **Expert craft:** say more than once that it must feel meticulously made.

Save the philosophy as a `.md` file.

## Step 2 — the conceptual seed

Before coding, find the conceptual thread in the original request.

It becomes a **subtle reference inside the algorithm**: refined, not literal.
Someone who knows the subject should feel it; anyone else simply sees a strong
generative piece. The philosophy is the computational language; the concept is
the quiet DNA in the parameters, behaviours and emergent patterns. Like a jazz
player quoting another tune through harmony — those who know will hear it, and
everyone enjoys the music.

## Step 3 — implement in p5.js

With the philosophy and concept settled, write the code. Pause and collect your
thoughts first.

### Read the template first

Before writing any HTML:

1. **Read** `templates/viewer.html`.
2. **Study** its structure: the header, the sidebar sections, the styling, the
   seed controls and action buttons.
3. **Copy it as your literal starting point**, not as inspiration.
4. **Keep the fixed parts** exactly as they are (layout, sidebar order, UI
   styling, seed controls, action buttons).
5. **Replace only the variable parts**, which the file's comments mark: the
   algorithm, the `params` object and the parameter controls.

Do not write the viewer from scratch, invent new UI styling, or change the
sidebar structure. The UI styling is the viewer's chrome; the art's own colors are
yours to choose.

`templates/generator_template.js` shows good structure for p5.js code
(parameters in one object, seeding, classes, utilities). Use it as reference, and
put your code inline in the HTML — no separate `.js` file.

### Technical requirements

**Seeded randomness.** Every run with the same seed must produce the same image:

```javascript
let seed = 12345;
randomSeed(seed);
noiseSeed(seed);
```

Use only p5's `random()` and `noise()` after seeding — never `Math.random()`.

**Parameters follow the philosophy.** Ask "what about this system should be
adjustable?" and expose those properties, not "pattern types":

```javascript
let params = {
  seed: 12345,
  // palette colors
  // quantities: how many?
  // scales: how big, how fast?
  // probabilities: how likely?
  // ratios: what proportions?
  // angles: which direction?
  // thresholds: when does behaviour change?
};
```

**The algorithm follows the philosophy.** Do not ask "which pattern should I
use?" Ask "how does this philosophy become code?"

- *Organic emergence* suggests things that accumulate or grow over time, random
  processes held by natural rules, feedback and interaction.
- *Mathematical beauty* suggests geometric relationships and ratios, trigonometry
  and harmonics, exact calculations that produce surprising patterns.
- *Controlled chaos* suggests random variation inside strict limits,
  bifurcations and phase changes, order emerging from disorder.

The algorithm comes from the philosophy, not from a menu. Build what this
particular request calls for.

**Canvas.** Standard p5.js:

```javascript
function setup() {
  createCanvas(1200, 1200);
  // build the system
}

function draw() {
  // static (noLoop) or animated
}
```

### Craft

The algorithm should feel as if it came out of countless iterations by a master
generative artist. Tune every parameter. Every pattern should have a reason. This
is controlled chaos refined by expertise, not random noise.

- **Balance:** complexity without visual noise; order without rigidity.
- **Color:** a considered palette, never random RGB.
- **Composition:** hierarchy and flow even inside randomness.
- **Performance:** smooth; keep animated pieces near 60 fps.
- **Reproducibility:** the same seed always gives the same output.

### Output

1. **The philosophy** as `.md`.
2. **One HTML file** built from `templates/viewer.html`, containing p5.js (from
   the CDN), the algorithm, the controls and the UI. It opens in any browser with
   no setup.

## The viewer

`templates/viewer.html` is the foundation.

**Fixed — always keep as is:**

- the layout (header, sidebar, canvas area) and UI styling, including light and
  dark mode;
- the **Seed** section: the seed field, Previous and Next, Random, and jumping to
  a typed seed;
- the **Actions** section: Regenerate, Reset and Download PNG.

**Variable — make it yours:**

- the whole p5.js algorithm (setup, draw, classes);
- the `params` object;
- the **Parameters** section: how many controls, their names, min/max/step,
  control types;
- the **Colors** section, which is optional: add color pickers if the palette
  should be adjustable, or remove the section for fixed or monochrome palettes.

Every piece has its own parameters and algorithm; the fixed parts give a
consistent experience around them.

### Required behaviour

1. **Parameter controls** — sliders for numbers, color pickers for palette
   colors, live updates when values change, and Reset restoring the defaults.
2. **Seed navigation** — the current seed shown; Previous/Next step through
   seeds; Random picks one; typing a seed jumps to it. When asked for "100
   variations", seeds 1–100 are the set.
3. **One file** — no external files or imports except the p5.js CDN script.
4. **Controls wired up** — each parameter has a control group like:

```html
<div class="control">
  <label for="density">Density <output id="density-value">0.5</output></label>
  <input type="range" id="density" min="0" max="1" step="0.01" value="0.5">
</div>
```

and an entry in the `CONTROLS` list in the script, which binds it to `params`.

### Using it

The HTML file runs as soon as it is opened. Give the person the path; if the
session can publish pages, offer to publish it. Sending the file is enough to
share it.

## Variations

Seed navigation already lets people explore. If they want particular variations
called out, add, in the same file:

- seed presets ("Variation 1: seed 42", "Variation 2: seed 127");
- a gallery mode showing thumbnails of several seeds side by side.

Like a run of prints from one plate: the algorithm stays the same, and each seed
shows another side of it.

## The process

**Request → philosophy → implementation.**

1. Understand what aesthetic the person wants.
2. Write the algorithmic philosophy (4–6 paragraphs).
3. Implement it.
4. Decide what should be adjustable.
5. Build controls for exactly those parameters.

Always the same: the viewer chrome, seed navigation, one self-contained file.
Everything else — the algorithm, the parameters, the controls, the result — is
new each time. Let the philosophy lead.

## Files

- `templates/viewer.html` — **required starting point** for every piece. Keep
  the layout, sidebar order, UI styling, seed controls and action buttons; replace
  the algorithm, `params`, and the Parameters and Colors controls. The comments
  mark what is which. Its flow-field sketch is only a placeholder: build what your
  philosophy demands.
- `templates/generator_template.js` — structure and good practice for p5.js
  code. Not a pattern catalogue.

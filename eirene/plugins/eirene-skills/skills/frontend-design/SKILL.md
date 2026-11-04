---
name: frontend-design
description: >
  Guidance for distinctive, intentional visual design when building new UI or
  reshaping an existing one: websites, landing pages, web apps, dashboards, app
  screens, components and HTML artifacts. Use it whenever you are about to build
  or restyle a page or screen people will look at, even if the request only says
  "build a site" or "make a page" and never mentions design, and alongside a
  theme or brand that sets the colors. Helps with aesthetic direction, typography,
  layout, motion and copy, and with making choices that don't read as templated
  defaults.
license: Apache-2.0. Complete terms in the LICENSE file at the root of this bundle.
---

# Frontend Design

Approach this as the design lead at a design studio known for giving every client
a distinct visual identity that is not mistaken for anyone else's. This client has
already rejected proposals that felt cliché or templated, and is paying for a
distinctive point of view: make deliberate, opinionated choices about palette,
typography and layout that are specific to this brief, and take aesthetic risk if
justified.

## Ground your designs in the subject matter

If the brief does not identify what the product or subject matter is, identify it
yourself before designing, and confirm with the person. You can come up with one
concrete subject, the design's audience and the design's primary job, as a
proposal. If you know anything about the person's preferences or what they are
building, use it as a hint. The subject's industry, subject matter, materials and
vernacular are where distinctive visual choices come from: a design for a toy for
children aged 8–11 will look very different from a dashboard for financial
analysts. Build with the brief's real content and subject matter throughout, not
lorem ipsum.

In an existing product, what is already established is part of the brief. Read
the project's components, tokens and pages first, keep what the person asked to
keep, and spend your choices where the brief leaves them open.

## Design principles

For web designs, the hero is the first thing viewers will see. Open with the most
characteristic thing in the subject's world, in the form that is most appropriate:
a headline, an image, an animation, a live demo, an interactive moment or another
treatment. Be deliberate with your choice: a big number with a small label,
supporting stats and a gradient accent is the default treatment, so only use it if
that is truly the best option.

Typography carries the personality of the page. You don't need a different typeface
for display or headline text and body content: use one family or two, and if two,
make them clearly distinct.

Choose your typefaces deliberately, not the default families you would reach for on
any other project, and set a clear type scale following the default guidance of
*The Elements of Typographic Style*, with intentional weights, widths and spacing.
When type is used as a headline or visual element, use the type treatment itself as
an active part of the design, not a neutral delivery vehicle for the content.

Default to line lengths of less than 80 characters. Serif typefaces can have
slightly longer line lengths; give serif body text slightly more line-height than a
sans-serif.

Avoid these default typographic treatments; they are the commonest tells of a
generated page:

- Accenting just a single word or phrase in a headline, like putting one word in
  italic or bold or a different color.
- Using all caps for labels.
- Adding unnecessary typographic labels above content.

Visual structure is information. Structural devices like outlines, borders,
numbering, eyebrows, dividers and labels encode useful information about the content
rather than decorate it. Many generic designs use numbered markers (01 / 02 / 03),
but that is only appropriate if the content actually is a sequence, like a stepped
process or a timeline. Before adding numbered markers, check the content really is a
sequence.

Use non-user-triggered motion sparingly and deliberately, only to draw attention. A
single orchestrated moment, such as one page-load sequence or one reveal, lands
better than scattered effects; fade-and-slide-up entrances on each section and hover
transitions on every card are the generic default and read as AI-generated. Motion
that answers a person's action (opening, expanding, confirming) is welcome when it
shows what changed.

Consider written content carefully. A design brief often does not contain real
content, and it is up to you to come up with copy and placeholder content. Copy can
make a design feel as templated as the design itself. See "More on writing in
design" below.

## Process: plan, review against the brief, build, critique

For calibration, AI-generated design right now clusters around some traits:

1. a warm cream background (near `#F4F1EA`) with a high-contrast serif display and
   a terracotta or warm-clay accent (often near `#D97757`);
2. a near-black background with a single bright acid-green or vermilion accent;
3. a broadsheet-style layout with hairline rules, zero border-radius and dense
   newspaper-like columns;
4. the SaaS-card kit: content chopped into identical rounded cards, one
   border-radius on everything regardless of hierarchy, the same soft grey shadow
   (`rgba(0,0,0,.1)`) under each, and gradient washes as decoration;
5. template chrome that appears whatever the subject: a tracked-out ALL-CAPS eyebrow
   label above every heading; meta strings joined with middle dots (`A · B · C`);
   labels built as `WORD — fragment` with a spaced em dash; tinted near-black
   (`#0B0B0B`, `#111`) standing in for black; a monospace face for small data
   labels; a `→` appended to link and button text.

All traits are legitimate for some briefs, but they are defaults rather than choices,
and they appear regardless of subject. Where the brief pins down a visual direction,
follow it exactly: the brief's own words always win, including when it asks for one
of these looks. Where it leaves an axis free, don't spend that freedom on one of
these defaults. As with a hired human designer, there is often a careful balance
between doing what you are good at and taking each project as a chance to experiment
and learn.

Work in two passes. First, brainstorm a short design plan based on the brief: create
a compact token system with color, type, layout and principles.

- **Color:** describe the core base palette as 4–6 named hex values.
- **Type:** the typefaces and their roles.
- **Layout:** a layout concept, using one-sentence prose descriptions and ASCII
  wireframes to ideate and compare. Include alignment guidance: should the content
  be left aligned, center aligned, justified?
- **Principles:** the high-level guidance for what makes this page unique.

Then review that plan against the brief before building. If any part of it reads
like the generic default you would produce for any similar page (work through a
similar prompt to see if you arrive somewhere similar) rather than a choice made for
this specific brief, revise that part and say what you changed and why. Only after
you have confirmed the relative uniqueness of your design plan should you start to
write the code, following the revised plan.

When writing the code, be careful of structuring your CSS selector specificities. It
is easy to generate CSS classes that cancel each other out, especially a type-based
selector like `.section` and an element-based selector like `.cta`. This happens
often with padding and margin between sections.

## Restraint and self-critique

Spend your boldness in one place. Let one element be the memorable thing, keep
everything around it quiet and disciplined, and cut any decoration that does not
serve the brief. Build to a quality floor without announcing it: responsive down to
mobile, visible keyboard focus, reduced motion respected, visually accessible,
harmonious color palettes.

Critique your own work as you build. If you can render the page and take screenshots
(for example with the `webapp-testing` skill), do it and look: a picture is worth
1000 tokens. Consider Chanel's advice: before leaving the house, take a look in the
mirror and remove one accessory. Human creatives have memory and always try to do
something new, so if you have a space to jot down notes about what you have tried,
it can help you in future passes.

## More on writing in design

Words appear in a design for one reason: to make it easier to understand and use.
They are design content, not decoration. Bring the same intentionality and minimalism
to copywriting that you would bring to spacing and color. Before writing anything,
ask what the design needs to say, and how it can best be said to help the person
navigate the experience.

Write from the end user's perspective. Name things by what users will understand in
simple language, not by how the system is built. A user manages notifications, not
webhook config. Describe what something is or does in plain terms rather than selling
it. Being specific and legible to new users is always better than being clever.

Use active voice as default. A CTA says exactly what happens when it is used: "Save
changes," not "Submit." An action keeps the same name through the whole flow, so the
button that says "Publish" produces a toast that says "Published." The vocabulary of
an interface is the signposting for someone navigating the product. Cohesion and
consistency are how people learn their way around.

Treat failure and emptiness as moments for direction, not mood. Explain what went
wrong and how to fix it, in the interface's voice rather than a person's. Errors don't
apologize, and they are never vague about what happened. An empty screen is an
invitation to act.

Keep the tone conversational: plain verbs, sentence case, no filler, with tone matched
to the brand and the audience. Let each written element do exactly one job.

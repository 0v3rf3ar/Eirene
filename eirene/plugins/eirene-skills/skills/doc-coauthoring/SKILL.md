---
name: doc-coauthoring
description: A structured workflow for writing a document together — specs, design docs, proposals, decision docs, RFCs, PRDs and similar. Gathers context efficiently, builds the document section by section, then tests it on a reader with no context. Use when someone wants to write or draft a substantial document.
---

# Co-authoring a document

A guided workflow for writing a document with someone. You lead them through
three stages: **gather context**, **build and refine**, and **test with a fresh
reader**.

## When to offer it

Offer the workflow when someone:

- asks to write a doc: "write a doc", "draft a proposal", "write up a spec";
- names a document type: PRD, design doc, decision doc, RFC, one-pager;
- is clearly starting a substantial piece of writing.

**The offer.** Describe the three stages in a sentence each:

1. **Context** — they tell you everything relevant; you ask clarifying
   questions.
2. **Build** — you create each section together through brainstorming and
   editing.
3. **Reader test** — a reader with none of this conversation's context tries the
   document, to catch blind spots before real readers do.

Explain that this helps the document work for people who read it cold, including
people who will paste it into an AI assistant. Ask whether they want the workflow
or would rather work freeform. If they decline, work freeform. If they accept,
start stage 1.

## Stage 1 — context

**Goal:** close the gap between what they know and what you know, so your later
suggestions are good ones.

### Opening questions

Ask about the document itself:

1. What kind of document is it (spec, decision doc, proposal…)?
2. Who is the main audience?
3. What should a reader think or do after reading it?
4. Is there a template or required format?
5. Any other constraints or context?

Tell them shorthand is fine and they can answer in any order.

If they mention a template or a document type, ask for the template. If they give
a link and you have a connector that can read it, read it; if they give a file,
read the file.

If they want to edit an existing document, read its current state. Check for
images without alt text: other readers (and AI assistants helping those readers)
cannot see them. Offer to write alt text; if they agree, ask them to share each
image.

### The context dump

Once the basics are answered, ask them to pour in everything they know, without
organising it:

- background on the project or problem;
- related discussions and documents;
- why the obvious alternatives were not chosen;
- organisational context (team dynamics, past incidents, politics);
- deadlines and constraints;
- technical architecture and dependencies;
- stakeholders' concerns.

They can dump it as a stream of thought, point you at channels or threads, or link
documents. If this session has connectors (chat, email, document storage, or MCP
servers that reach them), say you can pull context directly. If it has none,
say so and suggest they paste the relevant parts, or enable an MCP server for the
source with `/mcp`.

Tell them you will ask clarifying questions once they have done the first dump.

While they are giving context:

- When they mention a channel or document: if you can reach it, say you will read
  it now and do so; if not, say you cannot and ask them to paste it.
- When they mention a project or name you do not know, ask whether you should
  search the connected tools for it, and wait for a yes before searching.
- Keep track of what you have learned and what is still unclear.

### Clarifying questions

When they signal the dump is done (or after a substantial amount of context), ask
**5–10 numbered questions** about the gaps. Tell them they can answer in
shorthand ("1: yes, 2: see the #infra thread, 3: no — backwards compatibility"),
link more material, or keep dumping.

**Done when** your questions are about edge cases and trade-offs rather than
basics.

**Moving on:** ask whether there is anything else to add, or whether to start
drafting. Let them add more if they want. Then go to stage 2.

## Stage 2 — build and refine

**Goal:** write the document section by section through brainstorming, selection
and iteration.

Explain how each section will go:

1. you ask clarifying questions about what it should contain;
2. you brainstorm 5–20 candidate points;
3. they say what to keep, cut or combine;
4. you draft the section;
5. you refine it with targeted edits.

### Order and structure

If the structure is already clear, ask which section to start with. Suggest the
one with the most unknowns — for a decision doc usually the proposal itself, for
a spec usually the technical approach. Leave summaries for last.

If they do not know what sections they need, propose 3–5 that fit the document
type and template, and ask whether that works.

### The scaffold

Once the structure is agreed, create the document with every section heading and
a placeholder such as `[To be written]`:

- If they want the document somewhere specific (a shared docs connector, a page
  you can publish), create it there.
- Otherwise write a Markdown file in the working directory with a clear name,
  such as `decision-doc.md` or `technical-spec.md`.

Tell them where it is and that you will now fill in each section.

### Each section

**1. Questions.** Say you are starting on [section]. Ask 5–10 specific questions
about what it should cover. Shorthand answers are fine.

**2. Brainstorm.** List 5–20 numbered candidate points, depending on how complex
the section is. Look for things they mentioned earlier but may have forgotten,
and angles nobody has raised. Offer to brainstorm more.

**3. Select.** Ask what to keep, cut or combine, with a word on why so you learn
their priorities. Examples:

- "Keep 1, 4, 7, 9"
- "Cut 3 (same as 1)"
- "Cut 6 (readers already know this)"
- "Combine 11 and 12"

If they answer freeform ("looks good", "mostly, but…"), work out what they want
and carry on.

**4. Gaps.** Ask whether anything important is missing from the section.

**5. Draft.** Say you are drafting [section] from what they picked. Replace that
section's placeholder with an exact edit (`edit_file`), not by rewriting the
whole file. Then tell them it is drafted and ask them to read it and say what to
change; specific feedback helps you with the next sections.

With the first section, add: rather than editing the document themselves, they
should tell you what to change ("cut the X bullet — Y covers it", "tighten the
third paragraph"). That teaches you their style for the rest.

**6. Refine.** Apply each piece of feedback as a targeted edit; never reprint the
whole document. If they edited the file themselves and ask you to look, read it
and note what they changed — those edits show their preferences. Keep going
until they are happy.

**Quality check.** After three rounds with no substantial change, ask whether
anything can be removed without losing information. When the section is done,
say so and ask whether to move to the next one.

Repeat for every section.

### Near the end

At around 80% complete, re-read the whole document and check for:

- flow and consistency between sections;
- repetition or contradiction;
- generic filler;
- sentences that do not earn their place.

Give that feedback. When every section is drafted and refined, review the whole
document once more for coherence, flow and completeness, make final suggestions,
and ask whether to move to the reader test.

## Stage 3 — reader test

**Goal:** check that the document works for someone who has none of your
context.

Explain that this catches blind spots: things that are obvious to the authors and
confusing to everyone else.

### With delegation (`delegate_tasks` available)

Run the test yourself.

1. **Predict reader questions.** Write 5–10 questions a real reader would ask
   when they come to this document.
2. **Test.** For each question, delegate to a fresh agent that gets *only* the
   document text and the question — no summary of this conversation. Ask it to
   answer, say what was ambiguous, and say what knowledge the document assumes.
3. **Extra checks.** Delegate once more and ask for ambiguity, unstated
   assumptions and internal contradictions.
4. **Report and fix.** Summarise what the reader got right and wrong. List the
   issues, then go back to stage 2 for the sections that caused them.

### Without delegation

The person runs the test.

1. **Predict reader questions.** Write 5–10 questions a reader would realistically
   ask.
2. **Instructions.** Ask them to open a fresh conversation with an assistant of
   their choice (a new Eirene session works: `eirene` in another terminal, or
   `eirene -p` with the document piped in), give it only the document, and ask
   each question. For each, the reader should give its answer, what was unclear,
   and what the document assumes the reader already knows.
3. **Extra checks.** Also ask the reader:
   - "What in this document is ambiguous or unclear?"
   - "What knowledge does it assume the reader already has?"
   - "Are there contradictions or inconsistencies?"
4. **Iterate.** Ask what the reader got wrong or struggled with, and fix those
   sections.

### Done when

The fresh reader answers the questions correctly and raises no new gaps.

## Final review

When the reader test passes, say so. Before wrapping up:

1. Recommend they read it through themselves — it is their document and their
   name on it.
2. Suggest double-checking facts, links and technical details.
3. Ask whether it achieves the effect they wanted.

Offer one more review. Otherwise, say the document is complete and leave a few
tips:

- an appendix linking to how the document was developed can help readers;
- appendices add depth without bloating the main text;
- update the document as real readers give feedback.

## Guidance

**Tone:** direct and procedural. Explain why only when it changes what they do.
Do not sell the process; run it.

**Deviations:** if they want to skip a stage, ask whether to drop the workflow
and write freeform. If they seem frustrated, acknowledge it is taking a while and
suggest a faster path. They can always change the process.

**Context:** whenever something mentioned is unclear, ask straight away; do not
let gaps pile up.

**Editing:** create the scaffold once, make every later change as a targeted
edit, and say where the document is after each change. Keep brainstorm lists in
the conversation, not in the document.

**Quality over speed:** do not rush the stages. Each round should make the
document better for its readers.

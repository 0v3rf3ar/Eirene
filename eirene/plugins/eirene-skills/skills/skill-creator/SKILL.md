---
name: skill-creator
description: Create new skills, improve existing ones, and measure how well they work. Use when someone wants to turn a workflow into a skill, write or edit a SKILL.md, test a skill against realistic prompts, benchmark it against a baseline, or tune its description so it triggers at the right times.
---

# Skill creator

A skill for making skills and improving them in a loop.

The process, roughly:

- decide what the skill should do and roughly how;
- write a draft;
- write a few realistic test prompts and run them with the skill (and without
  it, for comparison);
- review the results with the person, by looking and by measuring:
  - while the runs go, draft checkable assertions (or review existing ones) and
    explain them;
  - open the review page (`eval-viewer/generate_review.py`) so the person can look
    at outputs and numbers;
- rewrite the skill from their feedback and from anything the benchmark shows;
- repeat until it is good;
- grow the test set and try again at larger scale.

Your job is to work out where the person is in this process and help them move
forward. Someone who says "I want a skill for X" needs help pinning down X, a
draft, test cases, a way to evaluate, runs, and iterations. Someone with a draft
can go straight to testing. Someone who says "no evals, let's just iterate
together" gets exactly that.

Once the skill works (the order is flexible), you can also tune its description
so it triggers reliably; there is a separate script for that.

## Talking with the person

People of all backgrounds write skills — some have never used a terminal,
others are experienced engineers. Read the cues and match your language:

- "evaluation" and "benchmark" are usually fine;
- explain "JSON", "assertion" or "front matter" unless the person clearly knows
  them.

A short definition in passing is better than leaving someone lost.

## Creating a skill

### Capture the intent

Start from what the person wants. The conversation may already contain the
workflow to capture ("turn this into a skill"): then pull out the tools used, the
order of steps, corrections the person made, and the input and output formats,
and ask them to fill the gaps and confirm before you continue.

1. What should the skill let the agent do?
2. When should it be used — which requests, phrases, situations?
3. What does the output look like?
4. Should we set up test cases? Skills with checkable outputs (file conversions,
   data extraction, code generation, fixed workflows) benefit from them; skills
   with subjective outputs (tone, design) often do not. Suggest a default that
   fits, and let the person decide.

### Interview and research

Ask about edge cases, input and output formats, example files, what counts as
success, and dependencies. Hold off on test prompts until this is clear.

Use what this session can reach to come prepared — web search, documentation,
MCP servers, similar skills already installed (`/skills`) — delegating parallel
lookups with `delegate_tasks` when they are independent. The less the person has
to explain, the better.

### Write SKILL.md

Fill in:

- **name** — lowercase with hyphens, matching the folder name.
- **description** — *when* to use it and *what* it does. This is the main thing
  that decides whether the skill is used: the agent sees only names and
  descriptions until it loads a skill. Put every "when to use" here, not in the
  body. Agents tend to *under*-use skills, so make descriptions a little
  insistent. Instead of "Build simple dashboards for internal metrics", write
  "Build simple dashboards for internal metrics. Use this whenever someone
  mentions dashboards, charts of company data, KPIs or reporting views, even if
  they don't say 'dashboard'."
- **compatibility** — required tools or dependencies (optional, rarely needed).
- the body.

## Writing skills

### Anatomy

```
skill-name/
├── SKILL.md            required: front matter (name, description) + instructions
├── scripts/            code for deterministic or repetitive steps
├── references/         documents loaded only when needed
└── assets/             files used in the output (templates, icons, fonts)
```

### Loading in stages

Skills are loaded progressively:

1. **name and description** — always visible (about 100 words);
2. **the SKILL.md body** — loaded when the skill is used (ideally under 500 lines);
3. **bundled files** — read or run only as needed (any size; scripts can run
   without being read).

So:

- keep SKILL.md under about 500 lines; as you approach that, add a layer — move
  detail into `references/` and say exactly when to read which file;
- name each reference file in SKILL.md with a line on when it is needed;
- give reference files over about 300 lines a table of contents.

**One skill, several variants** — organise by variant so only the relevant part is
read:

```
cloud-deploy/
├── SKILL.md            workflow and how to choose
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

In Eirene, a skill's supporting files are reached relative to its folder (the
`load_skill` result says where the folder is); plugin skills can also use
`load_plugin_resource`.

### No surprises

Skills must not contain malware, exploits or anything that could compromise a
system. What a skill does should never surprise someone who reads a description
of it. Do not write skills meant to mislead, gain unauthorised access or move
data out without consent. Role-play personas and the like are fine.

### Patterns

Write instructions in the imperative.

**Output formats** — show the exact shape:

```markdown
## Report structure
Use this template:
# [Title]
## Summary
## Findings
## Recommendations
```

**Examples** — show input and output:

```markdown
## Commit messages
**Example:**
Input: added login with JWT tokens
Output: feat(auth): add JWT-based login
```

### Style

Explain *why* things matter instead of piling up MUSTs. Models today are capable
and understand intent; reasons generalise to cases you did not foresee, while
rigid rules break on them. Keep it general rather than tied to your examples.
Write a draft, then reread it as a stranger would and improve it.

### Test cases

After the draft, write 2–3 realistic test prompts — what a real person would
actually type. Share them: "Here are a few test cases I'd like to try. Do they
look right, or should we add some?" Then run them.

Save them in `evals/evals.json` inside the skill folder. No assertions yet — just
prompts; you draft assertions while the first runs are going.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {"id": 1, "name": "short-descriptive-name", "prompt": "the request", "expected_output": "what success looks like", "files": []}
  ]
}
```

Input files go in `evals/files/` and are listed relative to `evals/`.
`references/schemas.md` describes every field, including `assertions`.

## Running and evaluating

This section is one continuous sequence; do not stop halfway.

Results go in `<skill-name>-workspace/` next to the skill folder, organised by
iteration (`iteration-1/`, `iteration-2/`, …) and then by test case. The scripts
create the folders.

Paths to scripts below are relative to this skill's folder; run the Python ones
from it (`python -m scripts.NAME …`).

### Step 1 — start every run at once

When improving an existing skill, first snapshot it:
`cp -r <skill> <workspace>/skill-snapshot`.

Then run all test cases, with the skill and with the baseline, in one go:

```bash
python -m scripts.run_tests --skill <skill> --workspace <skill>-workspace            # new skill: baseline is no skill
python -m scripts.run_tests --skill <skill> --workspace <skill>-workspace \
    --baseline <skill>-workspace/skill-snapshot                                       # improving: baseline is the old copy
```

Each run is a separate `eirene -p` process with its own folder: the with-skill
run gets a copy of the skill at `./skill` and is told to follow it; the baseline
gets the same prompt without it. Other installed skills are switched off for both
(`--skills none`) so the comparison is clean. Runs go in parallel (`--parallel`,
default 3); use `--runs 3` for variance, `--model`/`--provider` to choose the
model, `--only ID …` to rerun some. Start it in the background (for example with
`start_process`) and carry on with step 2. Timing, tokens and tool counts are
recorded automatically in each run's `timing.json` and `metrics.json`.

If `eirene -p` cannot run here (no provider connected, or the provider runs its
own tools and cannot be restricted), run each test yourself instead: give a
delegated agent (`delegate_tasks`) the task plus "read `<skill>/SKILL.md` and
follow it", and a second one the task alone; save their files into the same
folder layout and write `timing.json` from what the delegation reports.

### Step 2 — draft assertions while the runs go

Use the waiting time. Draft checkable assertions for each test case and explain
them to the person; if assertions already exist, review and explain them.

Good assertions are objectively verifiable and named so that anyone glancing at
the results knows what each one checks. Subjective qualities (style, design) are
better judged by looking — do not force assertions onto them.

Add the assertions to each `eval_metadata.json` and to `evals/evals.json`. Tell
the person what they will see on the review page: the outputs, and the
benchmark numbers.

### Step 3 — grade, aggregate, open the review page

When every run is done:

1. **Grade each run.** Follow `agents/grader.md` — delegate one grader per run
   (in parallel) or grade inline — and write `grading.json` next to each run's
   `outputs/`. The `expectations` entries must use exactly `text`, `passed` and
   `evidence`. Check assertions that a script can check with a script: faster,
   more reliable, and reusable next iteration.

2. **Aggregate:**

   ```bash
   python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name> --skill-path <skill>
   ```

   This writes `benchmark.json` and `benchmark.md`: pass rate, time and tokens per
   configuration with mean ± stddev, and the difference.

3. **Look for patterns** the averages hide — follow "Benchmark patterns" in
   `agents/analyzer.md`: assertions that pass whatever the skill (not measuring
   anything), high-variance evals (possibly flaky), time and token costs. Add
   your notes to `notes` in `benchmark.json`.

4. **Open the review page** with outputs and numbers:

   ```bash
   python eval-viewer/generate_review.py <workspace>/iteration-N --skill-name <name>
   ```

   Run it in the background (`start_process`); it serves on
   http://127.0.0.1:3117 and opens a browser. From iteration 2 on, add
   `--previous-workspace <workspace>/iteration-(N-1)`. Without a display (a remote
   machine, a container), use `--static <workspace>/iteration-N/review.html` and
   give the person the file path — its Submit button downloads `feedback.json`,
   which they (or you) put in the iteration folder.

   Use this page rather than writing your own HTML. Open it **before** you start
   judging the outputs yourself — get them in front of the person quickly.

5. **Tell the person**, for example: "The results are open in your browser. The
   Outputs tab shows each test case with a feedback box; the Benchmark tab has the
   numbers. Tell me when you're done."

### What the page shows

**Outputs**, one test case at a time:

- the prompt;
- the files the with-skill run produced, rendered inline where possible;
- grades (collapsed), the transcript (collapsed);
- the baseline's output (collapsed);
- from iteration 2, the previous iteration's output (collapsed);
- a feedback box that saves as they type, and their feedback from last time.

**Benchmark**: pass rates, time and tokens per configuration, per-run results, and
your notes.

Arrow keys or the buttons move between cases. "Submit all reviews" saves
`feedback.json`.

### Step 4 — read the feedback

When the person says they are done, read `<workspace>/iteration-N/feedback.json`:

```json
{"reviews": [
   {"run_id": "two-page-invoice-with_skill", "feedback": "the totals lost their decimals", "timestamp": "…"},
   {"run_id": "scanned-invoice-with_skill", "feedback": "", "timestamp": "…"}],
 "status": "complete"}
```

Empty feedback means that output was fine; focus on the cases with complaints.
Stop the review server when you no longer need it.

## Improving the skill

This is the heart of the loop.

### How to think about it

1. **Generalise from the feedback.** The skill will be used on many prompts you
   will never see. You and the person iterate on a few examples because it is fast,
   but a skill that only works on those examples is useless. Avoid fiddly,
   over-fitted fixes and oppressive rules. When something stubborn will not budge,
   try a different framing, metaphor or way of working — it is cheap to try.

2. **Keep it lean.** Remove what is not pulling its weight. Read the transcripts,
   not just the outputs: if the skill makes the agent spend time on unproductive
   steps, cut the parts causing that and see what happens.

3. **Explain the why.** Work out what the person actually needs, even from terse or
   frustrated feedback, and put that understanding into the instructions. ALWAYS
   and NEVER in capitals, or rigid structures, are a warning sign: explain the
   reason instead, so the model can apply it sensibly.

4. **Bundle repeated work.** If every test run wrote a similar helper (a
   `make_chart.py`, a `build_docx.js`), the skill should ship that script once in
   `scripts/` and say when to use it.

Take your time here. Write a revision, then read it again fresh and improve it.
Put yourself in the person's position.

### The loop

1. Apply the improvements.
2. Rerun every test case into the next iteration, baseline included. For a new
   skill the baseline stays "no skill"; when improving one, choose between the
   original snapshot and the previous iteration.
3. Open the review page with `--previous-workspace`.
4. Wait for the person to finish reviewing.
5. Read the feedback, improve, repeat.

Stop when the person is happy, the feedback is all empty, or you are no longer
making real progress.

## Blind comparison (optional)

To answer "is the new version really better?" more rigorously: give two outputs to
an independent agent without saying which is which, and let it judge
(`agents/comparator.md`); then have another work out *why* the winner won
(`agents/analyzer.md`). It needs delegation, and most of the time the person's
review is enough.

## Tuning the description

The description decides when the skill is used. After creating or improving a
skill, offer to tune it.

### Step 1 — write trigger queries

Write 20 queries, a mix of should-trigger and should-not-trigger, as a JSON list:

```json
[
  {"query": "the request", "should_trigger": true},
  {"query": "another request", "should_trigger": false}
]
```

Make them realistic and specific — what someone would actually type, with file
paths, details of their situation, column names, company names, URLs, a bit of
backstory. Some lower-case, with abbreviations, typos or casual phrasing. Vary the
length. Favour edge cases over clear-cut ones (the person will review them).

Bad: `"Format this data"`, `"Extract text from PDF"`, `"Create a chart"`.

Good: `"ok so my boss sent me this xlsx (it's in my downloads, something like 'Q4 sales final FINAL v2.xlsx') and wants a column with profit margin as a percentage. revenue is column C and costs are D i think"`.

**Should trigger (8–10):** different phrasings of the same need, formal and casual;
cases where the person never names the skill or file type but clearly needs it;
some unusual uses; cases where this skill competes with another and should win.

**Should not trigger (8–10):** the valuable ones are near-misses — requests that
share words or ideas with the skill but need something else: neighbouring
domains, ambiguous phrasing that a keyword match would catch, cases where the skill
touches the topic but another tool fits better. "Write a fibonacci function" as a
negative for a PDF skill tests nothing.

### Step 2 — review them with the person

```bash
python -m scripts.review_queries --skill-path <skill> --eval-set <workspace>/trigger_evals.json
```

This opens a page where they can edit queries, flip should/should-not, add or
delete, and export. The export lands in their downloads folder as `eval_set.json`
(take the newest if there are several, such as `eval_set (1).json`). Bad queries
make bad descriptions, so this step matters.

### Step 3 — run the optimisation

Tell the person it takes a while and that you will run it in the background and
report progress. Save the final set in the workspace and start:

```bash
python -m scripts.optimize_description --eval-set <workspace>/trigger_evals.json \
    --skill-path <skill> --model <the model in use> --max-iterations 5 --verbose
```

Use the same provider and model the person normally works with, so the test
matches their experience. While it runs, check its output and tell them which
iteration it is on and how the scores look.

It splits the queries 60% train / 40% held-out test, scores the current
description (each query three times for a stable rate), asks the model for a
better description from the train failures, scores that on both sets, and repeats
up to five times. Each query runs as `eirene -p` in a private Eirene home with the
person's configuration and other skills plus the candidate, so it sees the same
competition as real use; a run counts as triggered when the model loads this
skill. At the end it opens an HTML report and prints JSON with
`best_description`, chosen by **test** score so it is not fitted to the train
queries.

### How triggering works

The agent sees each skill's name and description and loads a skill when it judges
it useful. It does not load skills for things it can do easily on its own — "read
this PDF" may not trigger a PDF skill however good the description, because one
tool call does it. Complex, multi-step or specialised requests trigger reliably
when the description fits. So trigger queries should be substantial enough that a
skill would genuinely help; trivial ones test nothing.

### Step 4 — apply it

Put `best_description` into the SKILL.md front matter, show the person the before
and after, and report the scores.

## Package or install

```bash
python -m scripts.quick_validate <skill>            # name, description, referenced files
python -m scripts.package_skill <skill> [out_dir]   # <name>.skill (a zip) to share
python -m scripts.package_skill <skill> --install   # copy into Eirene's skills folder
```

`--install` copies the skill into `~/.local/share/eirene/skills/<name>` (or under
`EIRENE_HOME`); it is then listed in `/skills`. An existing copy is kept unless you
add `--replace`. Give the person the path of whatever you produced.

## Updating an existing skill

- **Keep the name.** Use the folder name and `name` unchanged — `research-helper`
  stays `research-helper`, not `research-helper-v2`.
- **Edit a copy if the original is read-only.** Installed plugin skills are
  managed by the plugin; copy the folder somewhere writable, edit and test it
  there, then install it under the same name or hand it back.
- **Snapshot first** (`skill-snapshot/` in the workspace) so the old version can be
  the baseline.

## Files

- `agents/grader.md` — grading assertions against outputs.
- `agents/comparator.md` — blind A/B comparison.
- `agents/analyzer.md` — why one version won; patterns in benchmarks.
- `references/schemas.md` — every JSON format and the workspace layout.
- `scripts/run_tests.py`, `scripts/aggregate_benchmark.py`,
  `eval-viewer/generate_review.py` — run, measure, review.
- `scripts/trigger_eval.py`, `scripts/review_queries.py`,
  `scripts/optimize_description.py`, `scripts/improve_description.py` —
  description tuning.
- `scripts/quick_validate.py`, `scripts/package_skill.py` — check, package, install.

---

The core loop once more:

- work out what the skill is for;
- draft or edit it;
- run it on test prompts, with a baseline;
- review with the person: open the review page, look at the numbers;
- improve and repeat until you are both satisfied;
- package or install it.

If you keep a plan (`plan_update`), add these steps to it so none get skipped —
especially "open the review page so the person can see the test results".

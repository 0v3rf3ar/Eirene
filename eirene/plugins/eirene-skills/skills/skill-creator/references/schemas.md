# File formats

Every JSON file the skill-creator workflow reads or writes. The scripts and the
viewer read these field names exactly.

## Contents

- `evals/evals.json` — test prompts and assertions
- trigger eval set — queries for description testing
- workspace layout
- `eval_metadata.json`
- `timing.json`, `metrics.json` (written by `run_tests.py`)
- `grading.json` (written by the grader)
- `benchmark.json` (written by `aggregate_benchmark.py`)
- `feedback.json` (written by the review page)
- `comparison.json`, `analysis.json` (blind comparison)
- `history.json` (description optimisation)

## evals/evals.json

Lives in the skill folder (`SKILL/evals/evals.json`); not packaged.

```json
{
  "skill_name": "invoice-extractor",
  "evals": [
    {
      "id": 1,
      "name": "two-page-invoice",
      "prompt": "Pull the line items out of invoices/acme-2024-03.pdf into a CSV with columns item, qty, unit_price, total",
      "expected_output": "A CSV with 14 rows whose totals add up to 1,842.50",
      "files": ["files/acme-2024-03.pdf"],
      "assertions": [
        "outputs contains exactly one .csv file",
        "the CSV has the columns item, qty, unit_price, total in that order",
        "the CSV has 14 data rows",
        "the totals column sums to 1842.50"
      ]
    }
  ]
}
```

- `id` — a number, unique in the file.
- `name` — optional; becomes the result folder name (otherwise one is made from
  the id and prompt).
- `prompt` — what a real person would type.
- `expected_output` — a human-readable description of success.
- `files` — inputs, relative to the `evals/` folder; copied into each run's
  `outputs/` before it starts.
- `assertions` — objectively checkable statements; may start empty and be
  filled in while the first runs are going.

## Trigger eval set

A plain list, for `trigger_eval.py`, `optimize_description.py` and
`review_queries.py`:

```json
[
  {"query": "can you get the line items out of this supplier invoice pdf and into a spreadsheet? it's in ~/Downloads/inv_4471.pdf", "should_trigger": true},
  {"query": "merge these three PDFs into one and number the pages", "should_trigger": false}
]
```

## Workspace layout

```
SKILL-workspace/
├── skill-snapshot/                 copy of the skill before you started editing (when improving one)
├── iteration-1/
│   ├── two-page-invoice/
│   │   ├── eval_metadata.json
│   │   ├── with_skill/run-1/
│   │   │   ├── outputs/            the run's files
│   │   │   ├── skill/              the copy of the skill the run used
│   │   │   ├── transcript.md
│   │   │   ├── events.jsonl
│   │   │   ├── timing.json
│   │   │   ├── metrics.json
│   │   │   └── grading.json        added by the grader
│   │   └── without_skill/run-1/    (or old_skill/run-1/)
│   ├── benchmark.json
│   ├── benchmark.md
│   └── feedback.json
└── iteration-2/ …
```

## eval_metadata.json

```json
{"eval_id": 1, "eval_name": "two-page-invoice", "prompt": "…", "expected_output": "…",
 "files": ["files/acme-2024-03.pdf"], "assertions": ["…"]}
```

`run_tests.py` writes it from `evals.json`. Update `assertions` here (and in
`evals.json`) when you draft them.

## timing.json

```json
{"total_tokens": 84852, "duration_ms": 23332, "total_duration_seconds": 23.3}
```

Tokens are input plus output across the run, including delegated work.

## metrics.json

```json
{"tool_calls": {"read_file": 5, "write_file": 2, "run_command": 8}, "total_tool_calls": 15,
 "errors_encountered": 0, "output_chars": 12450, "status": "completed", "exit_code": 0}
```

`output_chars` is the total size of the files in `outputs/`. `status` and
`exit_code` come from the headless run (`completed`, `failed`, `incomplete`,
`timeout`; exit codes as in Eirene's headless documentation).

## grading.json

```json
{
  "expectations": [
    {"text": "the CSV has 14 data rows", "passed": true, "evidence": "items.csv: header plus 14 rows"}
  ],
  "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0},
  "execution_metrics": {"total_tool_calls": 15},
  "timing": {"total_duration_seconds": 23.3},
  "claims": [{"claim": "…", "type": "factual", "verified": true, "evidence": "…"}],
  "user_notes_summary": {"uncertainties": [], "needs_review": [], "workarounds": []},
  "eval_feedback": {"suggestions": [], "overall": "No suggestions; the evals look solid."}
}
```

Required: `expectations[]` with `text`, `passed`, `evidence`, and `summary`. Use
exactly these names — not `name`/`met`/`details`.

## benchmark.json

```json
{
  "metadata": {"skill_name": "invoice-extractor", "skill_path": "…", "timestamp": "2026-01-15T10:30:00Z",
               "evals_run": ["two-page-invoice"], "runs_per_configuration": 1},
  "runs": [
    {"eval_id": 1, "eval_name": "two-page-invoice", "configuration": "with_skill", "run_number": 1,
     "result": {"pass_rate": 1.0, "passed": 4, "failed": 0, "total": 4, "time_seconds": 42.5,
                "tokens": 38000, "tool_calls": 18, "errors": 0},
     "expectations": [{"text": "…", "passed": true, "evidence": "…"}],
     "notes": []}
  ],
  "run_summary": {
    "with_skill": {"pass_rate": {"mean": 0.85, "stddev": 0.05, "min": 0.8, "max": 0.9},
                   "time_seconds": {"mean": 45.0, "stddev": 12.0, "min": 32.0, "max": 58.0},
                   "tokens": {"mean": 38000, "stddev": 4000, "min": 32000, "max": 41000}},
    "without_skill": {"pass_rate": {"mean": 0.35, "stddev": 0.08, "min": 0.28, "max": 0.45},
                      "time_seconds": {"mean": 32.0, "stddev": 8.0, "min": 24.0, "max": 42.0},
                      "tokens": {"mean": 21000, "stddev": 3000, "min": 18000, "max": 25000}},
    "delta": {"pass_rate": "+0.50", "time_seconds": "+13.0", "tokens": "+17000"}
  },
  "notes": ["The skill adds about 13 s per run and raises the pass rate by 50 points."]
}
```

- `configuration` — `with_skill`, `without_skill` or `old_skill`.
- `result` holds the numbers; `pass_rate` is never at the top level of a run.
- `delta` — with_skill minus the baseline, as signed strings.
- `notes` — the analyser's observations; kept when the aggregator reruns.

## feedback.json

```json
{"reviews": [
   {"run_id": "two-page-invoice-with_skill", "feedback": "unit prices lost their decimals", "timestamp": "…"},
   {"run_id": "scanned-invoice-with_skill", "feedback": "", "timestamp": "…"}],
 "status": "complete"}
```

Empty feedback means the person was happy with that output.

## comparison.json

Written by the blind comparator; see `agents/comparator.md`. Key fields:
`winner` (`A`, `B` or `TIE`), `reasoning`, `rubric` (per side: `content`,
`structure`, `content_score`, `structure_score`, `overall_score`),
`output_quality`, and optionally `expectation_results`.

## analysis.json

Written by the analyser after a comparison; see `agents/analyzer.md`. Key fields:
`comparison_summary`, `winner_strengths`, `loser_weaknesses`,
`instruction_following`, `improvement_suggestions` (each with `priority`,
`category`, `suggestion`, `expected_impact`), `transcript_insights`.

## history.json

Written by `optimize_description.py`: one entry per iteration.

```json
[{"iteration": 0, "description": "…", "train_accuracy": 0.75, "test_accuracy": 0.625,
  "results": [{"query": "…", "should_trigger": true, "trigger_rate": 0.67, "triggers": 2, "runs": 3,
               "pass": true, "_test": true}]}]
```

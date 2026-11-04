# Analyser

Two jobs: explain **why** the winner of a blind comparison won, and spot
**patterns** in benchmark results that the averages hide.

## Part 1 — after a blind comparison

### Inputs

- **winner** — "A" or "B";
- **winner_skill_path**, **winner_transcript_path**;
- **loser_skill_path**, **loser_transcript_path**;
- **comparison_result_path** — the comparator's JSON;
- **output_path** — where to write the analysis.

### Process

1. **Read the comparison.** Note the winner, the reasoning and the scores: what
   did the comparator value?
2. **Read both skills** — SKILL.md and the key files it points to. Compare how
   clear and specific the instructions are, which scripts and tools they offer,
   their examples, and how they handle edge cases.
3. **Read both transcripts.** How closely did each run follow its skill? Which
   tools did they use differently? Where did the loser go wrong? Any errors or
   recoveries?
4. **Score instruction-following** for each, 1–10, with the specific lapses: did it
   follow explicit instructions, use the provided scripts, miss content it could
   have used, add steps nobody asked for?
5. **Winner's strengths** — clearer instructions, better scripts, examples that
   covered the edge case, better error guidance. Be specific; quote.
6. **Loser's weaknesses** — ambiguity that led to poor choices, missing tools that
   forced improvisation, gaps in edge cases, poor error handling.
7. **Suggestions** for improving the loser: concrete instruction changes, scripts to
   add or change, examples to include, edge cases to cover. Rank by impact —
   focus on what would have changed the outcome.
8. **Write** the analysis to `output_path`.

### Output

```json
{
  "comparison_summary": {"winner": "A", "winner_skill": "path/to/a", "loser_skill": "path/to/b",
                         "comparator_reasoning": "A filled every field; B missed the date"},
  "winner_strengths": ["A step-by-step check of every field against the form image",
                       "A validation script that caught overlapping boxes"],
  "loser_weaknesses": ["'Fill the form appropriately' left the method open; the run guessed coordinates",
                       "No validation step, so an overflow went unnoticed"],
  "instruction_following": {
    "winner": {"score": 9, "issues": ["Skipped the optional final render"]},
    "loser": {"score": 6, "issues": ["Did not use the bundled fill script", "Ignored the 'check boxes first' step"]}
  },
  "improvement_suggestions": [
    {"priority": "high", "category": "instructions",
     "suggestion": "Replace 'fill appropriately' with: extract structure, write fields.json, check boxes, fill, render",
     "expected_impact": "Removes the guesswork that caused misplaced text"},
    {"priority": "medium", "category": "tools",
     "suggestion": "Bundle a box-overlap checker and tell the skill to run it before filling",
     "expected_impact": "Catches overflow before output"}
  ],
  "transcript_insights": {
    "winner_execution_pattern": "read skill → extracted structure → checked boxes → filled → rendered and fixed one field",
    "loser_execution_pattern": "read skill → estimated positions → filled → no check"
  }
}
```

Categories: `instructions`, `tools`, `examples`, `error_handling`, `structure`,
`references`. Priorities: `high` (would likely change the result), `medium`
(better quality, maybe not the result), `low` (marginal).

### Guidelines

- Quote the skills and transcripts; do not just say "unclear".
- Make suggestions concrete changes, not advice.
- Improve the skill, not the agent.
- Check causation: did that weakness really cause the worse output?
- Prefer changes that would help on other test cases too.

## Part 2 — benchmark patterns

Here the aim is to **surface patterns and anomalies** across runs, not to suggest
skill changes.

### Inputs

- **benchmark_data_path** — `benchmark.json` with every run;
- **skill_path**;
- **output_path** — where to write the notes (a JSON list of strings).

### Process

1. **Read the benchmark**: configurations, per-run results, summary.
2. **Per assertion**, across runs:
   - always passes in both configurations → may not measure the skill's value;
   - always fails in both → may be broken or beyond reach;
   - passes with the skill, fails without → the skill clearly helps here;
   - fails with the skill, passes without → the skill may be hurting;
   - varies a lot → flaky assertion or non-deterministic behaviour.
3. **Across evals**: consistently hard or easy kinds of task; high variance on
   some; results that contradict expectations.
4. **Metrics** (time, tokens, tool calls): does the skill add a lot of time? High
   variance? Outlier runs skewing averages?
5. **Write notes**: each a specific, data-grounded observation that the averages do
   not show.

Examples:

- "'Output is a PDF' passes 100% in both configurations — it does not measure the skill."
- "Eval 3 varies widely (50% ± 40%); run 2 failed oddly and may be flaky."
- "Without the skill, every table-extraction assertion fails."
- "The skill adds about 13 s per run and raises the pass rate by 50 points."
- "Tokens are 80% higher with the skill, mostly from reading script output."
- "All three without-skill runs of eval 1 produced no file."

### Output

```json
[
  "'Output is a PDF' passes 100% in both configurations — it does not measure the skill.",
  "Eval 3 varies widely (50% ± 40%); run 2 failed oddly and may be flaky.",
  "The skill adds about 13 s per run and raises the pass rate by 50 points."
]
```

Then add these notes to the `notes` list in `benchmark.json` (the aggregator keeps
them when it reruns).

### Guidelines

- Report what you see in the data, not guesses.
- Be specific about which evals, assertions and runs.
- Point out what the averages hide.
- Leave improvement suggestions out of these notes.

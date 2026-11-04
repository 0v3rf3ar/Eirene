# Blind comparator

Decide which of two outputs better accomplishes a task **without knowing which
version of a skill produced which**. That keeps the judgment about the output,
not about the approach.

## Inputs

- **output_a_path** and **output_b_path** — files or folders;
- **eval_prompt** — the task that was run;
- **expectations** — assertions to check (may be empty).

## Process

### 1. Read both outputs

Examine A, then B. Note type, structure and content. For folders, look at every
relevant file; render documents and images if you can.

### 2. Understand the task

What must be produced? Which qualities matter — accuracy, completeness, format?
What separates a good result from a poor one here?

### 3. Build a rubric

Two dimensions, adapted to the task:

**Content**

| Criterion | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Correctness | major errors | minor errors | fully correct |
| Completeness | key parts missing | mostly complete | everything present |
| Accuracy | significant inaccuracies | small inaccuracies | accurate throughout |

**Structure**

| Criterion | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Organisation | disorganised | reasonable | clear and logical |
| Formatting | inconsistent or broken | mostly consistent | polished |
| Usability | hard to use | usable with effort | easy to use |

Replace criteria with task-specific ones where that is fairer — for a filled PDF
form, "field alignment", "legibility", "data placement"; for a document,
"section structure", "heading hierarchy", "flow"; for data, "schema
correctness", "types", "completeness".

### 4. Score both

For A and for B: score each criterion 1–5, average each dimension, and put the
overall score on a 1–10 scale (the mean of the two dimension averages × 2).

### 5. Check the assertions (if any)

Check each against A and against B and count pass rates. This is supporting
evidence, not the main deciding factor.

### 6. Pick the winner

In order: the overall rubric score; then assertion pass rate; a tie only if they
are genuinely equal. Be decisive — one output is usually better, even slightly.

### 7. Write the result

Save to the path you were given, or `comparison.json`.

## Output

```json
{
  "winner": "A",
  "reasoning": "A fills every field and aligns the text with the form lines; B leaves the date empty and its address overflows the box.",
  "rubric": {
    "A": {"content": {"correctness": 5, "completeness": 5, "accuracy": 4},
          "structure": {"organisation": 4, "formatting": 5, "usability": 4},
          "content_score": 4.7, "structure_score": 4.3, "overall_score": 9.0},
    "B": {"content": {"correctness": 3, "completeness": 2, "accuracy": 3},
          "structure": {"organisation": 3, "formatting": 2, "usability": 3},
          "content_score": 2.7, "structure_score": 2.7, "overall_score": 5.4}
  },
  "output_quality": {
    "A": {"score": 9, "strengths": ["complete", "well aligned"], "weaknesses": ["one label slightly cramped"]},
    "B": {"score": 5, "strengths": ["readable"], "weaknesses": ["date missing", "overflowing address"]}
  },
  "expectation_results": {
    "A": {"passed": 4, "total": 5, "pass_rate": 0.8, "details": [{"text": "Date filled", "passed": true}]},
    "B": {"passed": 3, "total": 5, "pass_rate": 0.6, "details": [{"text": "Date filled", "passed": false}]}
  }
}
```

Leave `expectation_results` out when there are no expectations. `winner` is
`"A"`, `"B"` or `"TIE"`.

## Guidelines

- Stay blind: do not guess which skill made which output, and do not let a guess
  sway you.
- Be specific: point to the exact strengths and weaknesses.
- Be decisive: ties are rare.
- Quality first: assertion scores come second to the overall result.
- Be fair: judge what the task asked for, not your preferred style.
- Explain the decision so it can be checked.
- Handle edge cases: if both fail, choose the one that fails less badly; if both
  are excellent, choose the slightly better one.

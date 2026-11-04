# Evaluating an MCP server

## At a glance

- Write **10** questions a person would really ask.
- Every question is **read-only, independent and non-destructive**.
- Each needs **many tool calls** — sometimes dozens.
- Each has **one verifiable answer**, checked by string comparison.
- Answers are **stable**: they will not change over time.

```xml
<evaluation>
  <qa_pair>
    <question>Your question</question>
    <answer>The single verifiable answer</answer>
  </qa_pair>
</evaluation>
```

## Why

A server is not good because it wraps many endpoints. It is good when a model
with no other context, using only its tools — their schemas, descriptions and
behaviour — can answer realistic, difficult questions. The evaluation measures
exactly that.

## Questions

### The basics

1. **Independent.** No question depends on another's answer or on anything another
   question changed.
2. **Read-only and idempotent.** Answering must not require changing state.
3. **Realistic, clear, concise and hard.** Another model should need several —
   possibly dozens — of tool calls to answer.

### Depth

4. **Multi-hop.** Chain sub-questions, where each step depends on what the last
   one found.
5. **Paging.** Some questions should need several pages of results, or older data
   (a year or two back) to find something specific.
6. **Understanding, not lookup.** Ask about ideas, not strings: true/false claims
   that need evidence, or multiple choice that needs several hypotheses checked.
7. **Not solvable by keyword search.** Avoid the exact words in the target content.
   Use synonyms and paraphrase so the model must search, read related items and
   reason.

### Stress the tools

8. **Large and varied results.** Questions that make tools return big lists or
   objects, and that need different kinds of data: IDs and names; dates and times
   (months, days, years, seconds); file IDs, names, extensions and MIME types;
   URLs.
9. **Real use.** Mostly the kinds of lookups a person helped by an assistant would
   actually want.
10. **Long tasks.** Some questions can need dozens of calls; that rewards tools that
    return only what is needed.
11. **Some ambiguity.** A few questions may make the choice of tool unclear or invite
    a misreading — but still have exactly one correct answer.

### Stability

12. **Answers must not drift.** Do not ask about live state: current counts of
    reactions, replies, members, open issues. Ask about things that are closed —
    finished projects, archived channels, past releases — or a fixed time window.
13. **Do not let the tools limit your questions.** Write the hard questions a person
    would ask, even if the current tools make them difficult; that is how you find
    what is missing.

## Answers

1. **Checkable by exact string comparison.** If the answer could be written several
   ways, say the format in the question: "Use YYYY-MM-DD", "Answer True or
   False", "Answer A, B, C or D only". Good answer types: a user or display name,
   a channel name, a message text, a URL or title, a number, a date, a boolean, an
   email address, a file name, a multiple-choice letter.
2. **Human-readable** where possible — names, dates, titles, yes/no — rather than
   opaque IDs (IDs are acceptable occasionally).
3. **Stable.** Base them on closed events; be specific enough that later content
   cannot match too (for example, a paper's title plus its year).
4. **Unambiguous.** Exactly one correct answer, reachable with the tools.
5. **Varied.** Across the ten, use different kinds of answer: names, IDs, dates,
   counts, text.
6. **Not lists or objects** — unless the order and format are completely fixed by
   the question. Ask for a count or a superlative instead of a list.

## Process

1. **Read the service's documentation** to understand what it offers. Look things up
   on the web where unclear. Split this across sub-agents (`delegate_tasks`) when it
   is large.
2. **Inspect the tools** — names, input and output schemas, descriptions — without
   calling them yet.
3. **Repeat 1–2** until you understand the service well. Do **not** read the
   server's source code; write questions as a user of the tools would.
4. **Explore the content** with read-only calls only, to find specific things to ask
   about. Keep calls small: use `limit` below 10 and paginate; some tools can
   return a lot. Parallelise independent explorations with sub-agents, each told to
   stay read-only.
5. **Write the ten questions** following the rules above.
6. **Verify.** Answer each question yourself with the tools (in parallel where you
   can). Correct any wrong answers, and drop any question that turned out to need a
   write.

## Good questions

**Multi-hop across history**

```xml
<qa_pair>
  <question>Which repository archived during Q3 2023 had been the organisation's most-forked project before it was archived? Give its primary language.</question>
  <answer>Python</answer>
</qa_pair>
```

It needs a search for archived repositories, a comparison of fork counts, then the
repository's details. The answer is short and based on closed history.

**Context without keywords**

```xml
<qa_pair>
  <question>Find the initiative about making new customers' first week easier that finished in late 2023. Its lead wrote a retrospective afterwards. What was the lead's job title at the time?</question>
  <answer>Product Manager</answer>
</qa_pair>
```

The project is described, not named; the model must find it, its lead and a
document.

**Aggregation**

```xml
<qa_pair>
  <question>Of the critical bugs reported in January 2024, which assignee resolved the highest share of theirs within 48 hours? Give the username.</question>
  <answer>alex_eng</answer>
</qa_pair>
```

Filtering by date and priority, grouping by assignee, time arithmetic, paging.

**Across data types**

```xml
<qa_pair>
  <question>Which account moved from the Starter plan to Enterprise in Q4 2023 with the largest annual contract value? What industry is it in?</question>
  <answer>Healthcare</answer>
</qa_pair>
```

## Poor questions

**Drifts over time**

```xml
<qa_pair>
  <question>How many open issues are assigned to the engineering team?</question>
  <answer>47</answer>
</qa_pair>
```

**One keyword search**

```xml
<qa_pair>
  <question>Who created the pull request titled "Add authentication feature"?</question>
  <answer>developer123</answer>
</qa_pair>
```

**Unfixed list format**

```xml
<qa_pair>
  <question>List the repositories whose main language is Python.</question>
  <answer>repo1, repo2, data-pipeline</answer>
</qa_pair>
```

Ask "how many" or "which has the most stars" instead.

## Running the harness

`scripts/evaluation.py` sends each question to Eirene as a separate headless run
with only the server under test granted, then compares the `<response>` it gives
with the expected answer.

### Setup

1. Add the server to Eirene with `/mcp add` (or in `config.json`), enable it in
   `/mcp`, and check that its tools appear.
2. Make sure a tool-capable provider is connected (`/connect`). Providers that run
   their own tools (Claude Code, Codex subscription) cannot be restricted to the
   granted server, so they fail with a configuration error; use an API provider.
3. Nothing else to install: the script uses only the Python standard library.

### Run

```bash
python scripts/evaluation.py questions.xml --server example -o report.md
python scripts/evaluation.py questions.xml --server example --provider openai --model MODEL --parallel 3
```

| Option | Meaning |
| --- | --- |
| `--server NAME` | MCP server to grant, as shown in `/mcp`; repeat for several |
| `--provider`, `--model` | the model under test (default: the active one) |
| `--timeout SECONDS` | limit per question (default 600) |
| `--max-steps N` | stop a run after N tool rounds |
| `--parallel N` | questions to run at once |
| `--ignore-case` | compare answers case-insensitively |
| `--eirene PATH` | which `eirene` executable to use |
| `--command CMD` | test a different agent: it gets the prompt on stdin and prints its reply |
| `-o FILE` | write the Markdown report to a file |

Each run is `eirene -p … --mcp NAME --tools read --stream-json` in an empty
temporary folder, so the model has the MCP tools and nothing else worth using.
Naming the server with `--mcp` is what approves its tools for the unattended run.
If the first question cannot start (unknown server, a server that fails to start,
no provider, rejected key), the harness stops and says why. A stdio server runs in
Eirene's sandbox, so give it `read_paths` for anything it needs outside the
project, such as its virtual environment. The exit status is 0 only when every answer is
correct.

### The report

- accuracy, average time and tool calls per question, total tokens;
- a table of expected and actual answers;
- for each question: the tools used and how often, the model's account of its
  approach, and its **feedback on the tools**.

Read the feedback and the tool counts together. Many calls for a simple question
usually means a missing filter or a tool returning too little; failures with long
outputs usually mean a tool returning too much. Fix the server, rebuild, and run
again.

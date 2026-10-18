---
description: Implement an approved Evecta plan and verify the result
argument-hint: <step-number>
allowed-tools: Read, Edit, Write, Glob, Grep, Bash, Skill
---

# Implement an approved plan

Implement one approved plan without expanding its scope. Follow `CLAUDE.md`.

User input: `$ARGUMENTS`

## 1. Validate the gate

Normalize the step to two digits and locate exactly one matching plan and its
referenced spec.

Stop when:

- the plan or spec is missing or ambiguous;
- either file lacks `status: approved`;
- the plan contains unresolved product decisions;
- the plan has no Task order;
- repository behavior has materially changed since the plan was written; or
- the plan conflicts with a project constraint.

Read the full spec, plan, and relevant source files. Preserve unrelated working
tree changes; the pipeline's own files under `.claude/` are not unrelated
changes and do not block a run.

## 2. Implement

Follow the plan's task order and stay within its scope. Read the spec once for
intent, then work from the plan.

Match the surrounding code — the naming, structure, comment density, and
SQLAlchemy 2.0 and Pydantic v2 idioms already in this codebase. Read
neighbouring files before adding to them.

For UI work, follow the plan's UI decisions rather than redesigning them, and
keep to what this project builds with: React 18, TypeScript, Vite, Tailwind, and
the components already in `Frontend/src/shared`. Consult `frontend-design` only
where the plan left a visual detail unspecified — the approved direction is
settled, and implementation is not the place to revisit it.

Find an unrelated bug, and record it as a follow-up rather than fixing it.

**Corrections travel in one direction.** Three cases, and they are not
interchangeable:

- **The plan is technically wrong or infeasible.** Update the plan first, state
  the correction and why, then continue. This is expected.
- **The required behavior is wrong or missing.** Stop and return to the spec.
  Never decide product behavior here.
- **A task is blocked on input that does not exist yet** — content, a corpus,
  credentials, a labelled dataset. Stop that task, name it, and change nothing.
  The plan is not wrong, so do not rewrite it to route around the gap. Complete
  every task that does not depend on the missing input, then report.

Never diverge silently. A divergence that is not written down is a defect in the
process, not a shortcut.

## 3. Project constraints

`CLAUDE.md` is the authority when it exists at the repository root or in
`backend/`. It does not exist yet, so until it does, treat the following as the
constraint set.

The Evecta backend is FastAPI, SQLAlchemy 2.0, Alembic, Celery, and Redis on
PostgreSQL with PostGIS. LangChain, LangGraph, `langchain-text-splitters`, and
Gemini through `langchain-google-genai` are already available.

Add no dependency the approved plan does not name. A dependency the plan names
as a task may be added to `requirements.txt` and installed into `env/` — that is
implementing the plan, not expanding it. Anything else, including a PostgreSQL
extension, stops the run.

Do not commit and do not push. `dev` is shared and a push deploys staging; leave
the working tree for the author to review.

## 4. Verify

Run focused tests while developing, then run all three from `backend/`:

```text
env/Scripts/python.exe -m pytest tests/ -q
env/Scripts/python.exe -c "import app.main"
env/Scripts/python.exe -m alembic check
```

On Linux or CI, the same three with `python`. Each answers a different question:
the suite passes; the application actually boots, so imports resolve, routes
register, and settings validate; and no model has drifted from its migration.

When the spec sets a **Retrieval quality bar**, the evaluation harness named in
the plan is a fourth required gate. Run it and record the score against the
floor. A feature that passes the suite but misses its floor is not implemented.

Tests must never construct a real `ChatGoogleGenerativeAI` or reach Google. The
`llm` object is passed as a parameter through the chat services, so substitute a
stub at that boundary.

Verification may never be skipped, faked, or substituted. If a gate cannot run
at all, that is a blocked run, not a passed one.

## 5. Close the lifecycle

Append `## Outcome` to the plan on every run that wrote code, whether it
finished or not:

```markdown
## Outcome

<Implemented | Blocked>: YYYY-MM-DD

### Verification
- pytest: <result, counts>
- import app.main: <result>
- alembic check: <result>
- evaluation harness: <score against floor>   (retrieval features only)

### Completed
Tasks finished, by number.

### Blocked
Tasks not attempted, each with what it waits on. Omit when none.

### Deviations from plan
What changed during implementation and why. "None" is a valid answer.

### Follow-ups
Unrelated issues found and deliberately not fixed.
```

Change the spec status and the plan status to `implemented` **only** when every
task is complete and every gate is green.

On a blocked or failing run both files stay `approved`, and completed work stays
in the tree — do not revert it. Report which gate or task stopped the run, with
the real output.

Report:

```text
Plan:        .claude/plans/<step>-<slug>.md
Result:      implemented | blocked | failed
Files:       <count> new, <count> modified
Migration:   applied | none
Verification: pytest <r> | import <r> | alembic <r> | harness <r>
```

List changed files and any remaining risk beneath the report. Never claim
completion when a check fails or a task was skipped.

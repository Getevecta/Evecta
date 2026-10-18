---
description: Create an implementation plan from an approved Evecta spec
argument-hint: <step-number>
allowed-tools: Read, Write, Glob, Grep, Skill
---

# Create an implementation plan

Turn an approved specification into a concise technical plan. Decide **how** the
feature will be built without changing requirements or application code.
Follow `CLAUDE.md`.

User input: `$ARGUMENTS`

## 1. Validate the specification

Normalize the step to two digits and locate exactly one matching file at
`.claude/specs/<step>-*.md`.

Stop when:

- no spec or multiple specs match;
- frontmatter does not contain `status: approved`;
- material Open questions remain;
- the spec sets a Retrieval quality bar with no committed numeric floor;
- the feature already appears implemented; or
- the spec conflicts with a project constraint.

An approved spec that still carries material open questions is an approval
mistake. Say so rather than designing around it.

Read the full approved spec and only the repository files needed to design the
change. Plan against code you have read, never against assumptions. Do not
reread unrelated specs.

## 2. Decide whether UI design is needed

A feature is **UI-bearing** when it adds or materially changes a rendered page,
section, form, or component in `Frontend/`.

For UI-bearing work, invoke the `frontend-design` skill in planning mode to
decide **how it should look** — visual direction, palette, type pairing,
hierarchy, and the one element the page is remembered by.

Constrain whatever it returns to **what this project can build**: React 18 with
TypeScript and Vite, Tailwind, `react-router-dom`, the spacing and typography
systems already documented at the repository root, and components already in
`Frontend/src/shared`. No new build step and no new UI dependency. A design this
project cannot build is not a design.

Return:

- the chosen mode (Consistency or Redesign);
- the visual direction, named, with its palette, type pairing and surface levels;
- layout and hierarchy, including what is deliberately loudest and what is quiet;
- reused components, responsive behavior, interaction, and accessibility decisions;
- no component code.

If a genuinely missing design pattern is identified, stop and ask for a decision
or reference. Backend-only work skips this section entirely.

## 3. Design proportionately

Cover only applicable areas:

- SQLAlchemy models and Alembic migrations;
- routers, dependencies, and authorization;
- Pydantic schemas and validation;
- services and domain logic;
- Celery tasks and scheduling;
- frontend surfaces;
- tests and verification.

Omit irrelevant sections instead of filling the plan with repeated "None."

Map acceptance criteria to tests by behavior group; do not create one test per
cosmetic criterion.

Tests must never construct a real `ChatGoogleGenerativeAI` or reach Google. The
`llm` object is passed as a parameter through the chat services, so a stub is
substituted at the call boundary. No test in `backend/tests/` currently
exercises an LLM path, so a feature that needs one must state its stubbing
approach in the plan rather than assume a pattern exists.

Name the verification commands the plan will be held to, run from `backend/`:

```text
env/Scripts/python.exe -m pytest tests/ -q
env/Scripts/python.exe -c "import app.main"
env/Scripts/python.exe -m alembic check
```

`pytest` is absent from `requirements.txt` and from the virtualenv. When the
plan adds tests, adding pytest is a task in its own right.

If implementation requires changing a requirement, stop and return to the spec.
Design gaps are fixed here; behavior gaps are fixed in the spec. Never decide
product behavior in a plan.

## 4. Project constraints

`CLAUDE.md` is the authority when it exists at the repository root or in
`backend/`. It does not exist yet, so until it does, treat the following as the
constraint set.

The Evecta backend is FastAPI, SQLAlchemy 2.0, Alembic, Celery, and Redis on
PostgreSQL with PostGIS. LangChain, LangGraph with the Postgres checkpointer,
`langchain-text-splitters`, and Gemini through `langchain-google-genai` are
already available and are preferred over anything new.

Do not plan in a standalone vector database service, a second web framework, a
second task queue, a second ORM, or an additional model provider. Prefer
extending the PostgreSQL instance already running over introducing a new store.

A required PostgreSQL extension is an infrastructure change, not a code change:
name it, and flag it for approval before implementation. Staging and production
share a host.

Report the conflict and stop rather than designing around a constraint.

## 5. Write and save the plan

Use:

```yaml
---
step: <step>
feature: <slug>
status: draft
spec: ../specs/<step>-<slug>.md
ui_bearing: true | false
---
```

```markdown
# Plan: <title>

## Summary
The implementation approach, the main design decision, and the alternatives
rejected with reasons. A reviewer must be able to disagree with this section.

## UI design decisions
Include only for UI-bearing features.

## Technical changes
Group changes by the applicable areas above. Name files and concrete technical
decisions here. For each file, state new or modified and what changes.

## Data model and migrations
Include only when the schema changes. Tables, columns, indexes, and the Alembic
revisions required. State whether each migration is reversible and whether it is
safe against a populated staging database.

## Tenancy and access
Include only when the feature reads or writes tenant-scoped data. Name the
filter that scopes every read path, and show that it applies inside the query
rather than to results afterward.

## Evaluation harness
Include only when the spec sets a Retrieval quality bar. How the evaluation set
is stored, how it is run, and the command that prints the score. It must be
runnable before the feature can be called done.

## Testing and verification
Map behavior groups to focused tests, naming the criteria each group covers and
the test file. List the verification commands.

## Task order
A short dependency-ordered implementation sequence. Mark tasks that require a
migration to run first.

## Risks and decisions
Remaining implementation risks and the cheapest way to find each out early.
Product questions are not allowed here; return those to the spec.
```

Keep small plans small. A one-component change should normally need a short
plan, not an exhaustive architecture document.

Save to `.claude/plans/<step>-<slug>.md`. If it exists, ask whether to review,
replace, or cancel. Write no file other than the plan, and do not modify
application code.

Confirm before saving that every functional requirement maps to at least one
task, and that every acceptance criterion maps to a behavior group.

Report:

```text
Plan file:  .claude/plans/<step>-<slug>.md
Spec:       .claude/specs/<step>-<slug>.md
UI-bearing: yes | no
Migration:  yes | no
New deps:   <names or none>
Status:     draft
```

List any requirement you could not map to a task beneath the report.

Tell the user to review the plan and change `status: draft` to
`status: approved` before running `/implement-plan <step>`.

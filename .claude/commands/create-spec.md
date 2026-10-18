---
description: Create a proportionate requirements spec for an Evecta feature
argument-hint: <step-number> <feature-name> [--full]
allowed-tools: Read, Write, Glob, Grep
---

# Create a feature specification

Create requirements only: define **what** the feature must do and how a reviewer
can verify it. Do not design or implement it. Follow `CLAUDE.md`.

User input: `$ARGUMENTS`

## 1. Identify and validate the feature

Derive:

- `step`: a two-digit number (`6` becomes `06`);
- `title`: short Title Case;
- `slug`: lowercase kebab-case, `a-z`, `0-9`, and `-`, at most 40 characters;
- `mode`: `full` when `--full` is supplied or the feature is high risk;
  otherwise `lite`.

Ask only when the step or feature cannot be inferred. Read `CLAUDE.md` when it
exists, the names of existing specs, and only the repository files needed to
understand what the system does today. Write the change as a delta from that
baseline, not from an assumed one.

Stop when the feature:

- is already complete;
- conflicts with a project constraint;
- is too broad to review as one feature; or
- duplicates an existing step.

Suggest a smaller boundary when scope is too broad.

Use **full mode** for ownership, tenancy, permissions, destructive behavior,
migrations, external integrations, security-sensitive flows, and broad
multi-surface features. Use **lite mode** for isolated UI, copy, navigation,
read-only displays, and small behavior changes. When uncertain, use lite mode
and surface the risk in Open questions instead of inflating the document.

## 2. Write the spec

Start every spec with:

```yaml
---
step: <step>
feature: <slug>
status: draft
spec_mode: lite | full
---
```

### Lite structure

```markdown
# Spec: <title>

## Summary
The user problem, the feature boundary, and what happens today in the same area.

## Goals and non-goals
### Goals
- ...
### Non-goals
- ...

## Requirements
- `FR-1: ...`

State observable inputs, outputs, state changes, validation, user feedback,
and, for user-facing work, essential keyboard and accessibility behavior. Do
not prescribe implementation.

## Acceptance criteria
- `AC-1` — Given ..., when ..., then ...

Cover each important requirement without creating a separate criterion for
every cosmetic detail.

## Dependencies and open questions
### Dependencies
- ...
### Open questions
- `Q-1` — the decision to be made; the options; what each option costs.
```

State the options and their consequences, not the question alone, so the author
can settle each one in a single pass. Write `None` only when there are
genuinely none.

### Full structure

Use the lite structure plus these sections where they add distinct information:

```markdown
## Users and scenarios
## Business rules
## User experience and failure behavior
```

Number business rules as `BR-1`, `BR-2`, and so on. Use multiline
Given/When/Then criteria only when the scenario needs that clarity.

### Retrieval quality bar

Required when the feature ranks, retrieves, or searches. Omit it otherwise.

Ranked output has no pass or fail state that Given/When/Then can express, so
state it as data:

```markdown
## Retrieval quality bar
- Evaluation set: how many real queries, and where they come from.
- Correct result: what counts as the right answer for a query.
- Floor: the measured bar committed to before implementation begins.
```

A retrieval feature without a numeric floor cannot reach `status: approved`,
and `/create-plan` will refuse it.

## 3. Requirements boundaries

Requirements may describe a public URL only when it is part of the product
contract. Do not specify:

- models, fields, migrations, schemas, routers, services, tasks, functions, or
  filenames;
- packages, architecture, pseudocode, commands, or implementation steps;
- files to change, test-file layout, estimates, or task breakdowns.

Naming an external system the product must interoperate with is a requirement,
not a design choice, and is permitted.

Put unresolved product decisions in Open questions. Do not silently decide
them. A spec with material open questions stays `draft`.

State each quality expectation once, in the section that owns it.

## 4. Project constraints

`CLAUDE.md` is the authority when it exists at the repository root or in
`backend/`. It does not exist yet, so until it does, treat the following as the
constraint set.

The Evecta backend is FastAPI, SQLAlchemy, Alembic, Celery, and Redis on
PostgreSQL with PostGIS. LangChain, LangGraph, and Gemini are already present.
A requirement must not oblige the project to add a standalone vector database
service, a second web framework, a second task queue, a second ORM, or an
additional model provider.

Report the conflict and stop rather than writing a requirement that needs one.

## 5. Quality check and save

Read the finished spec once as a reviewer who has not seen this conversation,
and confirm:

- the boundary is clear from Goals and non-goals alone;
- every requirement is observable from outside the system, and necessary;
- no acceptance criterion passes by inspecting an implementation detail;
- every decision left unmade appears in Open questions; and
- the document is proportionate to the feature.

Save to `.claude/specs/<step>-<slug>.md`. If it exists, ask whether to review,
replace, or cancel; never overwrite silently. Write no file other than the
spec, and do not modify application code.

Report only:

```text
Spec file: .claude/specs/<step>-<slug>.md
Mode:      lite | full
Status:    draft
Open:      <count>
```

List each open question beneath the report, numbered as in the spec.

Tell the user to review the spec, resolve open questions, and change
`status: draft` to `status: approved` before running `/create-plan <step>`.

# Template + Variation Engine (Pipeline Stage #3)

The Template + Variation Engine owns the markdown **writing-rules knowledge base** and the
**variation logic** that keeps outreach emails from looking repetitive. It sits between the
Personalization Level Engine (#2) and AI Email Generation + Compliance (#4).

```
#1 Lead Information Collector
        ↓
   Context Enrichment
        ↓
#2 Personalization Level Engine   →  decides personalization_level (from plan) + tone (user choice)
        ↓
#3 Template + Variation Engine    →  THIS MODULE: picks structure + variants + rules → "writing spec"
        ↓
#4 AI Email Generation + Compliance Checker  →  turns the spec into a prompt, calls the LLM, runs spam gate
```

**Stage #3 does NOT call the LLM and does NOT run the spam/compliance gate.** It decides *how*
an email should be written and hands that decision to stage #4.

---

## Status & Roadmap

### ✅ Done — core engine complete, integrated with pipeline

| Piece | What it does |
|---|---|
| **`rules/*.md` knowledge base** | 11 markdown files: spam-safe rules (tiered), 8 structures, 5 greetings, 9 CTAs, 6 closings, phrasing (quality + rhythm), 5 tones |
| **`loader.py`** | Parses + caches the YAML-frontmatter rules; typed accessors for every pool |
| **`variation.py`** | Deterministic round-robin selection per lead — reproducible, guaranteed spread, decorrelated axes; level-limited structures + tone→CTA guard |
| **`spec_builder.py`** | Bundles the variant recipe + tone block + rules + level-filtered lead context into a `WritingSpec` for #4 |
| **`prompt_builder.py`** | Renders `WritingSpec` into LLM prompt instructions |
| **`writing_spec_service.py`** | Bridges Step #2 → #3; builds per-lead specs for campaigns |
| **`repetition.py`** | Shingle-based Jaccard similarity guard to flag near-duplicate drafts for re-roll |
| **Pipeline wiring** | `campaign_draft_service` + `ai_email_generator` consume `WritingSpec`; personalization preview API returns per-lead variant summary |

The full path works end-to-end: `lead → resolve_personalization (#2) → build_spec (#3) → LLM prompt (#4 entry)`.

### ⏳ Remaining

| Item | Status | Why |
|---|---|---|
| **`scoring.py`** (Phase 4) | Placeholder — **blocked** | Needs variant metadata persisted per sent email + send history |
| **Per-lead generation loop** | Step #4 | Campaign draft still generates one template email; per-lead async generation uses `repetition.py` re-rolls |

### 🚧 `scoring.py` is blocked on two prerequisites

1. **Variant-per-email isn't persisted.** [`EmailActivity`](../models/email_activity.py) records
   `opened`/`replied`/`bounced` but not *which* structure/CTA/tone an email used. Stage #4 must
   save the variant metadata with each draft before performance can be attributed to a variant.
2. **No send history yet.** Weighting needs hundreds of measured sends; day one every variant
   has zero data and scoring would just fall back to the current round-robin.

So scoring is correctly last and partly depends on #4. Until then, round-robin variation is the
selection strategy.

### 💡 What can be done later (optional enhancements)

- **More variety, zero code:** add entries to any `rules/*.md` pool — combinations multiply.
- **Guaranteed uniqueness at scale:** switch `variation.py` from per-axis round-robin to
  **full-combination dealing** (shuffle the 8,640-space once, deal in order) so no recipe
  repeats until the whole space is used. Per-axis currently repeats a full recipe every
  `LCM(pool sizes)` leads.
- **Bigger tone→CTA guard:** extend `TONE_CTA_EXCLUDE_KEYWORDS` if new tone/CTA conflicts appear.
- **Repetition at large scale:** replace pairwise Jaccard with a MinHash/LSH index if campaigns
  get very large.
- **Phase 4 scoring:** once the two prerequisites above exist — aggregate `EmailActivity` by
  variant dimension and bias selection (e.g. epsilon-greedy) toward top performers.

---

## Inputs — what #3 receives from #2

#2 produces one **campaign-level personalization decision** plus the **enriched leads**.

| Field | Type | Allowed values | How #3 uses it |
|---|---|---|---|
| `tone` | str | `professional` \| `friendly` \| `casual` \| `partnership` \| `soft_intro` | **User's choice.** Loads `rules/tones/<tone>.md` |
| `plan` | str | `free` \| `starter` \| `growth` \| `scale` | The **source** of the personalization level (see mapping below) |
| `personalization_level` | str | `minimal` \| `standard` \| `deep` \| `research` | **Not raw input — derived from `plan` by #2** via the fixed Plan → Level mapping. #3 consumes it to scale variation richness + context depth |
| `leads` | list[dict] | per lead: `business_name`, `industry`, `address`, `services`, `website_summary`, `business_description` | Per-lead context for generation |
| `user_profile` | dict | `full_name`, `bio`, `department`, `location` | Sender identity |
| `company_profile` | dict | `company_name`, `company_description`, `products_and_services` | Sender's company |

> **Note:** `personalization_level` is a deterministic mapping from `plan`, not independent
> data. #2 (the Personalization Level Engine) performs that mapping and hands #3 the resolved
> level. The `plan → level` table should live as **one shared constant** that both #2 and #3
> import, so the two stages can never drift.

Proposed shared shape (produced by #2, consumed by #3):

```python
@dataclass
class PersonalizationOutput:
    tone: str                  # professional | friendly | casual | partnership | soft_intro
    personalization_level: str # minimal | standard | deep | research
    plan: str                  # free | starter | growth | scale
    leads: list[dict]
    user_profile: dict
    company_profile: dict
```

---

## Tone vs Personalization Level — two separate knobs

| Knob | Decided by | Why |
|---|---|---|
| **Tone** | The **user** (a dropdown choice) | A preference; costs nothing extra to honor |
| **Personalization level** | The **plan** (automatic) | Cost control — deeper personalization = more enrichment/compute, so it's a paid tier benefit |

The user does **not** choose the personalization level. A free user always gets `minimal`;
deeper levels are what they upgrade for. This is the spec's stated purpose for #2:
*"cost control + predictable AI behavior."*

### Plan → Level mapping (owned by #2, not #3)

```
free    → minimal
starter → standard
growth  → deep
scale   → research
```

This mapping lives in the **Personalization Level Engine (#2)**. Stage #3 never reads the
plan — it only reacts to the resolved `personalization_level` string it is handed.

### Level → Behavior (owned by #3)

What each level *does* inside the variation engine:

| Level | Plan | Structures in pool | Lead context injected | Variation strength |
|---|---|---|---|---|
| `minimal` | free | 1–2 | name + industry only | light |
| `standard` | starter | full pool | + address + services | normal |
| `deep` | growth | full pool | + website summary + description | normal |
| `research` | scale | full pool | + any researched fields | richest |

---

## Outputs — what #3 hands to #4

A **writing spec**: the chosen structure + variants + tone block + applicable rules. Stage #4
turns it into a prompt. Shape lives in [`spec_builder.py`](./spec_builder.py) and must be
agreed with whoever owns stage #4 before implementation.

Stage #3 does **not** output: the final email (that's #4), the spam/compliance verdict
(that's #4), or any scraping/enrichment (that's #1).

---

## The markdown knowledge base (`rules/`)

Each `rules/*.md` file uses **YAML frontmatter** for machine-read config and a markdown body
for human guidance (tone files are prose only). Parsed by [`loader.py`](./loader.py) with
PyYAML — no custom regex. The per-file breakdown is in
[Files in this package](#rules--writing-rules-knowledge-base) below.

Editing rules is a **content change** (no code, no deploy): add a bullet under `variants:`,
add a key under `structures:`, or add a phrase to `prohibited_phrases:`.

---

## Files in this package

### Directory structure

```
email_engine/
├── __init__.py            # package docstring; overview of stage #3's role
├── README.md              # this document
├── loader.py              # reads + caches + parses the rules/*.md files
├── variation.py           # seeded round-robin variant selection / rotation (done)
├── spec_builder.py        # composes the writing spec (WritingSpec) for stage #4 (done)
├── repetition.py          # similarity guard against repetitive output (done)
├── scoring.py             # placeholder — Phase 4 performance-based variant weighting
└── rules/                 # the markdown writing-rules knowledge base
    ├── spam_safe.md       # prohibited phrases + deliverability rules (single source)
    ├── structures.md      # named email skeletons (id → ordered steps)
    ├── greetings.md       # greeting variants
    ├── ctas.md            # call-to-action variants
    ├── closings.md        # sign-off variants
    ├── phrasing.md        # sentence-pattern + tone-hygiene guidance
    └── tones/             # one tone block per file (plain prose, no frontmatter)
        ├── professional.md
        ├── friendly.md
        ├── casual.md
        ├── partnership.md
        └── soft_intro.md
```

### Python modules

| File | Status | Role |
|---|---|---|
| `__init__.py` | ✅ done | Marks the package; docstring summarizing stage #3's responsibilities |
| `loader.py` | ✅ done | Reads, caches (by mtime), and parses every `rules/*.md` file; exposes typed accessors (`get_prohibited_phrases`, `get_greeting_variants`, `get_structures`, `get_tone`, …) |
| `variation.py` | ✅ done | Picks one variant per axis via deterministic round-robin (shuffle per `campaign_seed`+axis, take `index % len`): reproducible, guaranteed spread, decorrelated axes. Limits structures by personalization level and applies the tone→CTA guard. Entry point: `select_variants(campaign_seed=, index=, tone=, personalization_level=)` → `VariantSelection` |
| `spec_builder.py` | ✅ done | Assembles the `WritingSpec` (variant recipe + tone block + rules + level-filtered lead context) handed to stage #4. Entry point: `build_spec(lead=, campaign_seed=, index=, tone=, personalization_level=, user_profile=, company_profile=)` → `WritingSpec` (with `.as_dict()`) |
| `repetition.py` | ✅ done | Shingle-based Jaccard similarity guard. `is_too_similar(candidate, others, threshold=0.6)` → bool; also `jaccard_similarity(a, b)` and `most_similar(candidate, others)`. Strips HTML + merge fields before comparing so shared placeholders don't inflate the score. Called by #4's generation loop to trigger a re-roll |
| `prompt_builder.py` | ✅ done | `format_writing_spec_prompt(spec)` → prompt section for stage #4 |
| `scoring.py` | ⏳ placeholder | Phase 4: will aggregate `EmailActivity` outcomes to weight variant selection toward top performers |

### `rules/` — writing-rules knowledge base

Each file is markdown with a **YAML frontmatter** block for machine-read config and a prose
body for human guidance (tone files are prose only).

| File | Frontmatter keys | Loader accessor | Description |
|---|---|---|---|
| `spam_safe.md` | `prohibited_phrases`, `spam_trigger_words`, `harmful_claim_phrases`, `aggressive_sales_phrases`, `openings_to_avoid`, `required_merge_fields`, `deliverability_rules` | `get_prohibited_phrases()`, `get_spam_trigger_words()`, `get_harmful_claim_phrases()`, `get_aggressive_sales_phrases()`, `get_openings_to_avoid()`, `get_required_merge_fields()`, `get_deliverability_rules()` | Single source of spam-safe rules, **tiered by strictness**: `prohibited_phrases` = HARD block (#4 rejects); `spam_trigger_words` = SOFT (generator avoids, gate only flags); plus harmful-claim / aggressive-sales lists and deliverability rules |
| `structures.md` | `structures` (map: id → `{label, description, steps}`) | `get_structures()`, `get_structure_ids()`, `get_structure_steps(id)` | 8 named email skeletons (`problem_solution`, `value_first`, `question_hook`, `short_intro`, `partnership`, `insight_share`, `social_proof`, `before_after`) rotated across leads. Each has a `description` (intent, injected into the prompt) and ordered `steps` |
| `greetings.md` | `variants` | `get_greeting_variants()` | Greeting-style directives; all preserve `{{ business_name }}` |
| `ctas.md` | `variants` | `get_cta_variants()` | Soft, low-pressure call-to-action variants |
| `closings.md` | `variants` | `get_closing_variants()` | Sign-off variants (always followed by the sender's name) |
| `phrasing.md` | `sentence_patterns`, `tone_hygiene`, `rhythm_variants` | `get_phrasing_hints()`, `get_rhythm_variants()` | Baseline quality hints applied to every email (`get_phrasing_hints`), plus `rhythm_variants` — one picked per email so phrasing feel varies lead-to-lead |

### `rules/tones/` — tone blocks

Plain markdown prose (no frontmatter). The whole body is returned by `get_tone(<name>)`. The
filename **is** the `tone` key #2 must send.

| File | `tone` key | Description |
|---|---|---|
| `professional.md` | `professional` | Formal, polished B2B tone; clarity and respect |
| `friendly.md` | `friendly` | Conversational, warm, approachable; still professional |
| `casual.md` | `casual` | Light and simple; no corporate jargon; relaxed but respectful |
| `partnership.md` | `partnership` | Frames the message as a mutual fit between equals, not a pitch |
| `soft_intro.md` | `soft_intro` | Gentle no-pressure first touch; lowest-commitment CTA |

---

## Coordination musts

1. **`tone` values must exactly match the tone filenames** (`professional`, `friendly`,
   `casual`, `partnership`, `soft_intro`). If #2's UI uses different labels, #2 normalizes
   them before handoff, or `loader.get_tone()` returns `""`.
2. **`personalization_level` is a fixed enum** (`minimal` / `standard` / `deep` / `research`).
   Both #2 and #3 must use the same four strings.
3. **`spam_safe.md` is the single source** for prohibited phrases — stage #4's compliance gate
   reads it too, so the generator and the gate never drift.

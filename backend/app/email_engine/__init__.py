"""
Template + Variation Engine (pipeline stage #3).

Sits between the Personalization Level Engine (#2) and AI Email Generation /
Compliance Checker (#4). Owns the markdown writing-rules knowledge base and the
variation logic; it does NOT call the LLM and does NOT run the spam/compliance
gate — it produces a "writing spec" that stage #4 consumes.

Public surface (filled in across phases):
    loader        -> read + cache the .md rules
    variation     -> seeded selection / rotation of variants across leads
    spec_builder  -> compose the writing spec handed to stage #4
    repetition    -> similarity guard to reduce repetitive output
    scoring       -> Phase 4: weight variant selection by campaign performance
"""

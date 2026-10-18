---
# Named email skeletons the variation engine rotates across leads so emails don't share
# the same shape. Each key is a selectable structure_id with:
#   label       - short human name
#   description - the structure's INTENT (injected into the prompt so the LLM writes to
#                 the purpose, not just the step order)
#   steps       - the paragraph order
# Shared constraints for ALL structures: open with Hi/Hello {{ business_name }},; use
# {{ industry }} and {{ address }} naturally; stay ~100-160 words; end with closing + name.
# CRITICAL: steps describe SHAPE only — every content paragraph must advance the USER REQUEST /
# campaign brief. Never invent a product pitch or value prop the user did not ask for.
structures:
  problem_solution:
    label: "Problem -> Solution"
    description: "Name a relevant challenge tied to the USER REQUEST, then advance the user's stated goal as the next step — do not invent a product pitch."
    steps:
      - Greeting
      - One-sentence specific observation about the recipient's {{ industry }} / {{ address }}
      - The challenge or need implied by the USER REQUEST
      - Advance the USER REQUEST goal (1-2 sentences — only what the user asked for)
      - Soft call to action aligned with the USER REQUEST
      - Closing + sender name
  value_first:
    label: "Value-First"
    description: "Open with a concrete point from the USER REQUEST, then briefly identify the sender."
    steps:
      - Greeting
      - Lead with the core point from the USER REQUEST, relevant to {{ industry }}
      - Brief reason it matters to the recipient
      - Light intro of who the sender is (identity only — not a new offer)
      - Soft call to action aligned with the USER REQUEST
      - Closing + sender name
  question_hook:
    label: "Question Hook"
    description: "Start with a relevant question tied to the USER REQUEST, then connect it to that same goal."
    steps:
      - Greeting
      - Open with a relevant question about their {{ industry }} situation tied to the USER REQUEST
      - Tie the question to the USER REQUEST goal (not a generic seller value-prop)
      - One supporting sentence from the brief
      - Soft call to action (offer to share more on the same topic)
      - Closing + sender name
  short_intro:
    label: "Short Introduction"
    description: "A brief, low-friction first touch: minimal text, one point from the USER REQUEST, an easy yes."
    steps:
      - Greeting
      - One-line reason for reaching out from the USER REQUEST (tied to {{ address }} / {{ industry }})
      - Single clear sentence advancing the USER REQUEST
      - Soft, low-commitment call to action
      - Closing + sender name
  partnership:
    label: "Partnership Angle"
    description: "Use only when the USER REQUEST is about partnership/collaboration; frame as mutual fit, not a sales pitch."
    steps:
      - Greeting
      - Frame the message as a potential mutual fit per the USER REQUEST
      - What a collaboration could look like based on the USER REQUEST
      - Why it's relevant to their {{ industry }}
      - Soft call to action (a brief conversation)
      - Closing + sender name
  insight_share:
    label: "Insight Share"
    description: "Open with a genuine observation about the recipient's {{ industry }}, then connect it to the USER REQUEST goal."
    steps:
      - Greeting
      - A specific, genuine insight or observation about their {{ industry }}
      - Why it matters to a business like theirs
      - How the USER REQUEST connects to that insight (do not invent a product offer)
      - Soft call to action
      - Closing + sender name
  social_proof:
    label: "Social Proof"
    description: "Reference the sender's relevant experience from the sender's profile and connect it to the USER REQUEST. Stay general - never invent specific clients, numbers, or results."
    steps:
      - Greeting
      - Brief, honest reference to the sender's relevant experience (no fabricated specifics)
      - Tie that experience to the recipient's {{ industry }} situation
      - How it supports the USER REQUEST goal
      - Soft call to action
      - Closing + sender name
  before_after:
    label: "Before / After"
    description: "Contrast a common current-state challenge in their {{ industry }} with a better outcome tied to the USER REQUEST — do not invent an unrelated product bridge."
    steps:
      - Greeting
      - Name a common current-state challenge in their {{ industry }} relevant to the USER REQUEST
      - Paint the better outcome the USER REQUEST points toward
      - How taking the next step on the USER REQUEST helps bridge the gap
      - Soft call to action
      - Closing + sender name
---

# Email Structures

The skeletons above are parsed by `loader.py` and rotated across leads by the variation
engine so a campaign's emails don't all share one shape.

- **Add a structure:** add a new key under `structures:` with `label`, `description`, and
  `steps`. No code change needed.
- **`description` matters:** it's injected into the generation prompt as the structure's
  intent, so write it as a clear instruction, not a label.
- The variation engine selects which structures are in play (e.g. the `minimal`
  personalization level uses a smaller subset); this file just defines the full catalogue.

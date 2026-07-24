---
name: document-quality
description: Use when creating DOCX reports, proposals, plans, and briefs. Enforces substantive structure, evidence mapping, readable hierarchy, and editable native content.
license: MIT
compatibility: opencode
metadata:
  artifact-type: docx
  capability-pack: document
---

# Document Quality

A document must help the declared audience understand or act. A valid Office archive is not a finished report.

## Planning

1. State the audience, purpose, central conclusion, and expected action.
2. Build a non-skipping heading hierarchy with unique conclusion-oriented headings.
3. Put the executive summary first for decision documents.
4. Map every factual section and table to evidence ids. Do not invent numbers or named facts.
5. Use paragraphs for reasoning, bullets for parallel facts, numbered lists for actions, and native Word tables for structured comparisons.

## Content gates

- Never ship `TODO`, `TBD`, `待补充`, lorem ipsum, test copy, or filler sections.
- Preserve every section explicitly named by the requirements contract as a real heading. Do not merge it into another heading or substitute a merely related heading.
- Keep one idea per paragraph and use direct, professional language.
- Table rows must match the declared headers.
- Recommendations must follow from the evidence and identify a concrete next action.
- Preserve the meaning of every observed metric. Never turn an observed metric into a target or commitment unless the evidence explicitly calls it one.
- Do not add a causal explanation or inferred root cause unless the cited evidence states that relationship. Keep correlation, timing, and hypotheses distinct.
- Do not write an unsupported status conclusion such as "on track", "meets expectations", or "significantly improved" when the evidence only reports events or measurements. State the observations and any remaining uncertainty instead.
- Keep content editable; do not flatten the report into screenshots.

## Specification

Top-level fields: `title`, optional `subtitle`, `audience`, `purpose`, optional `author`, and `sections`.

Each section has `kind`, `heading`, `level`, optional `paragraphs`, `bullets`, `numbered_items`, optional `table: {headers, rows}`, and `source_evidence_ids`. Supported kinds are `executive_summary`, `analysis`, `narrative`, `table`, `recommendations`, and `appendix`.

`paragraphs`, `bullets`, and `numbered_items` must each be a flat array of strings. Never put objects such as `{heading, level, items}` inside them. To add another heading, create another section with its own `heading`, `level`, and flat string arrays.

Call `create_document`, inspect the deterministic quality report, repair every failed check, and deliver only a verified editable DOCX plus its manifest.

---
name: image-quality
description: Use when creating PNG infographics, diagrams, posters, or social cards. Enforces semantic layout, readable text, contrast, safe bounds, and evidence mapping.
license: MIT
compatibility: opencode
metadata:
  artifact-type: image
  capability-pack: image
---

# Image Quality

This pack creates designed information graphics, diagrams, posters, and social cards. It does not create photorealistic scenes or pretend that deterministic drawing is a diffusion model.

## Plan by meaning

1. State the audience, purpose, and one visual takeaway.
2. Choose `infographic`, `diagram`, `social_card`, or `poster`.
3. Use at most six blocks. Each block must have a role: `process`, `callout`, `metric`, or `list`.
4. Map factual blocks to evidence ids and avoid unsupported numbers or claims.
5. Keep copy concise enough to be read on a phone; use the document capability for long prose.

Do not add a strong claim such as `立即`, `实时`, `始终`, `确保`, `保证`, `保障`, `保护`, `安全`, `泄露`, `控制权`, `删除`, `移除`, `加密`, `匿名`, `永远`, `绝不`, or `100%` unless the exact commitment is present in the cited evidence. This applies to titles, subtitles, blocks, and footers. The renderer rejects unsupported commitments instead of treating fluent copy as verified fact.

## Visual rules

- Use a restrained neutral background, dark readable text, one accent, and one semantic highlight.
- Treat the renderer's verified canvas and palette as fixed production defaults; the model owns content structure, not raw colors or dimensions.
- Minimum text contrast is 4.5:1 for primary copy.
- Do not solve overflow by making text illegibly small. The renderer rejects text that cannot fit.
- Do not use emoji or pictographic symbols because the production font may render them as missing-glyph boxes.
- Keep process labels concise. When a process card is too narrow for readable horizontal steps, use a vertical sequence instead.
- Every process step must be directly stated by the cited evidence. Do not invent intermediate, merge, return, or synchronization stages.
- In private-evidence strict mode, do not add an unsupported causal effect, comparison, or dependency. Wording such as `直接影响`, `决定`, `意味着`, `而非`, and `不只依赖` must be present in the cited evidence or removed.
- Do not use decorative gradients, bokeh, nested cards, or generic atmospheric imagery.
- Never ship placeholder text or a visually blank canvas.

## Specification

Top-level fields: `title`, optional `subtitle`, `purpose`, `audience`, `visual_kind`, `canvas`, `palette`, `blocks`, and optional `footer`.

Each block has `kind`, `heading`, optional `body`, optional `value`, optional `items`, and `source_evidence_ids`.

`items` must be a flat array of strings, never objects such as `{label, desc}`. Combine a label and description into one concise string. `footer` must be a single string, never an object or evidence container; factual footer text should be mapped through the relevant blocks instead.

Call `create_image`, inspect the deterministic pixel, contrast, bounds, font, and source checks, repair failures, and deliver only a verified PNG plus its manifest.

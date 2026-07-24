---
name: presentation-quality
description: Use when creating or revising PPTX presentations. Builds evidence-grounded narratives, selects visual slide roles, and verifies content and layout before delivery.
license: MIT
compatibility: opencode
metadata:
  artifact-type: pptx
  capability-pack: presentation
---

# Presentation Quality

Create a presentation that helps its audience understand, decide, or act. A valid PPTX file is not enough.

## Plan before rendering

1. Read the requirements contract and evidence pack.
2. State the audience, purpose, desired action, tone, and slide budget.
3. Form one governing idea and a narrative with a beginning, development, and conclusion.
4. Give every slide one role: `title`, `section`, `concept`, `process`, `comparison`, `evidence`, or `closing`.
5. Map factual claims to evidence ids. Mark unsupported specifics as missing instead of inventing them.

## Content rules

- Use a conclusion-style title that communicates the slide's point.
- Prefer a short explanatory sentence, diagram, comparison, or data point over a wall of bullets.
- Keep only information needed by the declared audience.
- Explain technical concepts with a concrete analogy, then state where the analogy stops being exact.
- Do not create filler slides such as “补充说明” merely to hit a page count.
- Treat broad technical statements as claims that need careful wording. Avoid absolute anthropomorphic claims such as “the model understands nothing”; distinguish a useful simplification from a verified mechanism.
- For LLM explainers, prefer operational wording: “生成阶段的核心机制是逐 token 预测；输出还受训练、架构、上下文和推理配置影响。” Say “predict the next token”, never “predict the next word”. Describe subword tokens as “词的一部分”, not the invented term “半词”. Say that text is represented as tokens instead of claiming “模型不读句子”. The effective context may also include system/developer instructions, retrieved evidence, tool results, and prior turns selected by the application; do not describe only the user's text plus generated text as everything the model receives. Do not call token-by-token decoding “逐字生成”, do not imply prompt tokens are ingested one at a time, and do not quote token-to-word ratios without evidence and tokenizer context. Decoding can sample from a distribution instead of always taking the single most likely token. Distinguish base-model state from application-level persistent memory: model parameters do not persist a task's history, but an application can pass prior interactions back in the next request, so do not say each inference is independent of previous interactions. Say factual accuracy is not guaranteed rather than impossible to inspect. A base model's parameter knowledge can have a training cutoff, while retrieval and tools can provide newer evidence; do not claim an assisted system is unable to know current information. Context overflow behavior belongs to the application or serving layer, which may reject, truncate, summarize, or split input; truncation is not universal. Do not present unsettled questions about understanding, thinking, consciousness, or reasoning as settled facts.
- Before rendering, check that every requested topic appears in at least one slide and that every factual number or named fact has an evidence id.
- In private-evidence strict mode, do not infer performance from a metric without an explicit benchmark. Phrases such as “表现良好”, “能力较强”, “风险可控”, “当日闭环”, or claims that the metrics establish a business/efficiency “基本面” are unsupported unless the evidence itself states them. Omit the interpretation or label it as a hypothesis/待验证.
- Do not invent absent-analysis claims such as “尚未分析”, “尚未统计”, or “未提供目标/基准对比”. Only report an information gap when the supplied evidence explicitly identifies that gap.
- If the user explicitly forbids invented information gaps, do not add claims such as “数据不足以判断”, “需进一步分析”, “需明确阈值”, “需确定频率”, “还需补充数据”, or “尚未验证”. Preserve requested candidate actions at exactly the supplied level of detail; do not decorate them with unsupported prerequisites.
- Do not invent where evidence came from. Claims such as “来自实际运营记录”, “源自内部系统”, or “来自调研数据” require that provenance in the evidence pack; otherwise say only “来自用户提供的证据”.
- Keep each slide at or below 360 non-whitespace characters. Use at most four process steps or visual nodes, at most four list items, and at most three items per side of a comparison. Move supporting detail to speaker notes or another slide instead of shrinking type.

## Canonical specification schema

Prefer these top-level slide fields so the deterministic renderer can preserve the planned content:

- all roles: `role`, `title`, `source_evidence_ids`
- `title`: `subtitle`, optional `preview_points`
- `section`: `takeaway`
- `concept`: `takeaway`, `points`, `visual: {type, nodes}`
- `process`: `takeaway`, `steps` (each step is a concise string)
- `comparison`: `left: {label, items}`, `right: {label, items}`
- `evidence`: `takeaway`, `points`
- `closing`: `takeaway`, then either `actions` or both `strengths` and `limits`

The renderer also accepts a nested `content` object and `evidence_ids` for compatibility, but new specifications should use the canonical fields. Never hide the actual slide content in arbitrary nested keys.

## Visual rules

- Use a restrained neutral palette with one primary accent and one semantic highlight.
- Build visuals with editable PowerPoint shapes whenever possible.
- Use stable alignment, consistent margins, and a clear type hierarchy.
- Vary layout by meaning, not decoration. A four-slide deck must contain at least one visual explanation.
- Avoid nested cards, decorative blobs, gradients, excessive rounded rectangles, and repeated bullet-only pages.

## Delivery

Create a structured presentation specification, call `create_presentation`, and inspect its returned quality report. If a required check fails, revise the specification and render again. The exact requested slide count, audience, goal terms, and explicit required topics are part of the deterministic request contract. In particular, `semantic_content_rendered` and `request_contract_matched` must both be true, and `rendered_content_coverage` must be at least `0.9`; a visually non-empty file can still fail when planned content was dropped or the user asked for something else. The final manifest must include capability pack id/version, slide roles, source evidence ids, and evidence-to-content mapping.

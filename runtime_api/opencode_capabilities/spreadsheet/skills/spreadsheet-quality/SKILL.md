---
name: spreadsheet-quality
description: Use when creating XLSX workbooks. Produces typed, formula-driven, auditable spreadsheets and verifies data semantics rather than file existence.
license: MIT
compatibility: opencode
metadata:
  artifact-type: xlsx
  capability-pack: spreadsheet
---

# Spreadsheet Quality

Build a workbook that supports a real decision. Read the goal, requirements, staged attachments, and evidence pack before creating a specification.

## Required planning

1. Define the workbook purpose and the question each sheet answers.
2. Preserve source rows; never invent missing numeric values.
3. Use typed columns and formulas for derived values instead of pasting calculated text.
4. Put raw/detail data before summaries. Give each evidence id an explicit sheet mapping.
5. Use short, unique sheet names, one header row, filters, and frozen headers.

## Formula rules

- Prefer simple auditable formulas: `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `IF`, `IFERROR`, and `ROUND`.
- Never use external links, web functions, macros, DDE, RTD, or hidden command execution.
- Avoid hard-coded totals when a formula can derive them.
- Prevent divide-by-zero with `IFERROR` or an explicit conditional.
- Ensure every generated formula has a deterministic preview value in the quality report.

## Specification

Top-level fields: `title`, `purpose`, optional `locale`, optional `currency`, and `sheets`.

Each sheet contains `name`, `description`, `columns`, `rows`, and `source_evidence_ids`. Each column has a unique `key`, a visible `label`, and a `type`: `text`, `integer`, `number`, `currency`, `percentage`, `date`, `datetime`, `boolean`, or `formula`. Formula columns also provide a formula template using `{row}` and should set `result_type` to `integer`, `number`, `currency`, or `percentage` so the calculated result is displayed with its business meaning.

Formula templates must use Excel A1 cell references. For columns A=`项目`, B=`收入`, C=`成本`, D=`利润`, and E=`利润率`, use `=B{row}-C{row}` with `result_type=currency` for profit and `=IFERROR(D{row}/B{row},0)` with `result_type=percentage` for margin. The renderer replaces only `{row}` with the Excel row number. 禁止使用 `{row}.revenue`, field names, JavaScript expressions, or any other non-Excel pseudo syntax.

Call `create_spreadsheet` and inspect the returned quality report. Repair unknown fields, unsafe formulas, missing source mapping, or incomplete formula previews. Deliver only a verified editable XLSX and its manifest.

# Deterministic Attachment Fixtures

Task 5 fixtures are generated inside pytest temporary directories. No fixture contains real user or personal data.

Expected semantic facts and stable locators:

| Format | Known fact | Required locator/result |
| --- | --- | --- |
| Rotated JPEG | EXIF orientation 6 on a 40x20 image | normalized preview is 20x40, max edge <= 2048 |
| Animated GIF | six frames with one duplicate | at most four distinct representative frames |
| Digital PDF | `Project Aurora ... 73000` | page 7 |
| Scanned PDF | blank/image-only page | page 1 marked suspected scan |
| DOCX | response time below 2 seconds | heading `验收标准`; table row and hyperlink retained |
| PPTX | revenue grew 42% | slide 12 notes |
| XLSX | cached value 125000 and formula `SUM(B2:B18)` | `预算!A2:D18` |
| CSV | renewal deadline 2026-08-20 | row range containing row 150 |
| TXT | password phrase `海盐拿铁` | UTF-8 and GB18030 decoding with lines 1-3 |
| Markdown | Python code block under `部署说明` | heading/code-block boundary; raw HTML is untrusted text |

Corrupt and encrypted examples are also generated at test time and must produce stable safe errors without filesystem paths.

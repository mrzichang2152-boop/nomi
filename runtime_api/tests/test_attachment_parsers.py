from __future__ import annotations

import io
import sys
import uuid
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.attachments.models import AttachmentRejected
from app.attachments.parsers import build_default_attachment_parser
from app.attachments.parsers.common import ParseResult, visual_cache_key
from app.attachments.parsers.docx import parse_docx
from app.attachments.parsers.image import parse_image
from app.attachments.parsers.pdf import parse_pdf, render_pdf_page
from app.attachments.parsers.pptx import parse_pptx
from app.attachments.parsers.spreadsheet import parse_csv, parse_xlsx
from app.attachments.parsers.text import parse_markdown, parse_text
from app.attachments.repository import AttachmentRecord, InMemoryAttachmentRepository
from app.attachments.worker import AttachmentWorker, AttachmentWorkerConfig, DraftCleaner
from app.attachments.queue import InMemoryAttachmentQueue


def _write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def _record(path: Path, parser_kind: str) -> AttachmentRecord:
    attachment_id = uuid.uuid4()
    return AttachmentRecord(
        attachment_id=attachment_id,
        client_upload_id=f"parser-{attachment_id}",
        original_filename=path.name,
        safe_filename=path.name,
        declared_mime_type=None,
        detected_mime_type=None,
        extension=path.suffix,
        byte_size=path.stat().st_size,
        sha256="b" * 64,
        storage_relative_path=path.name,
        status="stored",
        lifecycle="draft",
        parser_kind=parser_kind,
        processing_version="attachment-v1",
        error_code=None,
        error_detail_safe=None,
        created_at=datetime.now(timezone.utc),
        stored_at=None,
        processed_at=None,
        attached_at=None,
        expires_at=None,
        deleted_at=None,
    )


def _jpeg_with_orientation(path: Path) -> Path:
    image = Image.new("RGB", (40, 20), color=(20, 120, 200))
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, format="JPEG", exif=exif)
    return path


def _animated_gif(path: Path) -> Path:
    frames = [Image.new("RGB", (24, 16), color=color) for color in ["red", "green", "red", "blue", "yellow", "black"]]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return path


def _text_pdf(path: Path, pages: list[str]) -> Path:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = StreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)
    assert len(PdfReader(path).pages) == len(pages)
    return path


def _scanned_pdf(path: Path) -> Path:
    image = Image.new("RGB", (800, 1200), color="white")
    image.save(path, format="PDF", resolution=144)
    return path


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    relationship = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship)
    run = OxmlElement("w:r")
    value = OxmlElement("w:t")
    value.text = text
    run.append(value)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _docx(path: Path) -> Path:
    document = Document()
    document.add_heading("验收标准", level=1)
    document.add_paragraph("接口响应时间必须低于 2 秒。")
    link_paragraph = document.add_paragraph("参考：")
    _add_hyperlink(link_paragraph, "Nomi 规范", "https://example.com/nomi-spec")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "负责人"
    table.cell(0, 1).text = "状态"
    table.cell(1, 0).text = "王超"
    table.cell(1, 1).text = "已确认"
    document.save(path)
    return path


def _pptx(path: Path) -> Path:
    presentation = Presentation()
    for number in range(1, 32):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = f"第 {number} 张"
        slide.placeholders[1].text = f"内容 {number}"
        if number == 12:
            slide.notes_slide.notes_text_frame.text = "本季度收入同比增长 42%，来自续费。"
    presentation.save(path)
    return path


def _xlsx_with_cached_formula(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "预算"
    for row in range(2, 19):
        sheet.cell(row, 1, f"项目{row}")
        sheet.cell(row, 2, row * 1000)
        sheet.cell(row, 3, "CNY")
    sheet["D18"] = "=SUM(B2:B18)"
    workbook.create_sheet("说明")["A1"] = "年度预算"
    workbook.save(path)

    with zipfile.ZipFile(path, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}
    xml_name = "xl/worksheets/sheet1.xml"
    xml = files[xml_name].decode("utf-8")
    xml = xml.replace("<f>SUM(B2:B18)</f><v></v>", "<f>SUM(B2:B18)</f><v>125000</v>")
    files[xml_name] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in files.items():
            target.writestr(name, payload)
    return path


def test_image_applies_exif_orientation_and_bounds_gif_frames(tmp_path):
    jpeg = parse_image(_jpeg_with_orientation(tmp_path / "rotated.jpg"))
    gif = parse_image(_animated_gif(tmp_path / "animated.gif"))

    assert jpeg.manifest["normalized_width"] == 20
    assert jpeg.manifest["normalized_height"] == 40
    preview = next(item for item in jpeg.derivatives if item.kind == "preview")
    with Image.open(io.BytesIO(preview.payload)) as rendered:
        assert rendered.size == (20, 40)
        assert max(rendered.size) <= 2048
    frames = [item for item in gif.derivatives if item.kind == "gif_frame"]
    assert gif.manifest["frame_count"] == 6
    assert 1 < len(frames) <= 4
    assert len({item.content_hash for item in frames}) == len(frames)


def test_pdf_preserves_page_locator_and_flags_scanned_pages(tmp_path):
    pages = [f"ordinary page {number}" for number in range(1, 22)]
    pages[6] = "Project Aurora launch budget is 73000 dollars"
    digital = parse_pdf(_text_pdf(tmp_path / "digital.pdf", pages))
    scanned_path = _scanned_pdf(tmp_path / "scan.pdf")
    scanned = parse_pdf(scanned_path)
    rendered = render_pdf_page(scanned_path, page_number=1, max_edge=1024)

    fact = next(chunk for chunk in digital.chunks if "73000" in chunk.text)
    assert fact.locator == {"page": 7}
    assert digital.manifest["page_count"] == 21
    assert digital.requires_default_visual_sweep is False
    assert scanned.manifest["suspected_scan_pages"] == [1]
    assert scanned.metrics["pages"][0]["text_char_count"] == 0
    assert rendered.kind == "pdf_page"
    with Image.open(io.BytesIO(rendered.payload)) as page_image:
        assert max(page_image.size) <= 1024


def test_docx_preserves_heading_table_and_hyperlink_locators(tmp_path):
    result = parse_docx(_docx(tmp_path / "requirements.docx"))

    paragraph = next(chunk for chunk in result.chunks if "低于 2 秒" in chunk.text)
    table = next(chunk for chunk in result.chunks if "王超" in chunk.text)
    link = next(chunk for chunk in result.chunks if "example.com/nomi-spec" in chunk.text)
    assert paragraph.locator["heading"] == "验收标准"
    assert table.locator["table"] == 1
    assert table.locator["row"] == 2
    assert link.locator["paragraph"] >= 1
    assert result.manifest["table_count"] == 1


def test_pptx_preserves_slide_and_notes_locator(tmp_path):
    result = parse_pptx(_pptx(tmp_path / "deck.pptx"))

    revenue = next(chunk for chunk in result.chunks if "42%" in chunk.text)
    assert revenue.locator == {"slide": 12, "section": "notes"}
    assert result.manifest["slide_count"] == 31
    assert result.requires_default_visual_sweep is False


def test_xlsx_formula_and_value_keep_sheet_range(tmp_path):
    result = parse_xlsx(_xlsx_with_cached_formula(tmp_path / "budget.xlsx"))

    budget = next(chunk for chunk in result.chunks if "125000" in chunk.text)
    assert "=SUM(B2:B18)" in budget.text
    assert budget.locator["sheet"] == "预算"
    assert budget.locator["range"] == "A2:D18"
    assert result.manifest["sheet_count"] == 2


def test_long_csv_is_bounded_and_keeps_row_range(tmp_path):
    rows = ["id,name,note"] + [f"{index},item-{index},ordinary" for index in range(1, 201)]
    rows[150] = "149,critical,renewal deadline 2026-08-20"
    path = _write(tmp_path / "records.csv", "\n".join(rows).encode())

    result = parse_csv(path)

    fact = next(chunk for chunk in result.chunks if "2026-08-20" in chunk.text)
    assert fact.locator["row_start"] <= 150 <= fact.locator["row_end"]
    assert result.manifest["row_count"] == 201
    assert all(len(chunk.text) <= 32_000 for chunk in result.chunks)


@pytest.mark.parametrize(
    ("encoding", "expected_encoding"),
    [("utf-8", "utf-8"), ("gb18030", "gb18030")],
)
def test_text_detects_encoding_and_keeps_line_numbers(tmp_path, encoding, expected_encoding):
    path = _write(tmp_path / f"note-{encoding}.txt", "第一行\n暗号是海盐拿铁\n第三行".encode(encoding))

    result = parse_text(path)

    fact = next(chunk for chunk in result.chunks if "海盐拿铁" in chunk.text)
    assert fact.locator == {"line_start": 1, "line_end": 3}
    assert result.manifest["encoding"].lower().replace("_", "-") == expected_encoding


def test_markdown_keeps_heading_and_code_block_as_untrusted_text(tmp_path):
    markdown = "# 部署说明\n普通文字\n```python\nprint('safe')\n```\n<script>alert(1)</script>\n"
    result = parse_markdown(_write(tmp_path / "readme.md", markdown.encode()))

    code = next(chunk for chunk in result.chunks if "print('safe')" in chunk.text)
    html = next(chunk for chunk in result.chunks if "script" in chunk.text)
    assert code.locator["heading"] == "部署说明"
    assert code.locator["code_block"] is True
    assert html.locator["trusted_html"] is False


def test_registry_dispatches_every_v1_parser(tmp_path):
    registry = build_default_attachment_parser()
    fixtures = [
        (_jpeg_with_orientation(tmp_path / "a.jpg"), "image"),
        (_text_pdf(tmp_path / "a.pdf", ["hello"]), "pdf"),
        (_docx(tmp_path / "a.docx"), "docx"),
        (_pptx(tmp_path / "a.pptx"), "pptx"),
        (_xlsx_with_cached_formula(tmp_path / "a.xlsx"), "xlsx"),
        (_write(tmp_path / "a.csv", b"a,b\n1,2"), "csv"),
        (_write(tmp_path / "a.txt", b"hello"), "txt"),
        (_write(tmp_path / "a.md", b"# hello"), "md"),
    ]

    for path, kind in fixtures:
        result = registry.parse(_record(path, kind), path)
        assert isinstance(result, ParseResult)
        assert result.manifest["parser_kind"] == kind


def test_corrupt_and_encrypted_files_return_stable_safe_errors(tmp_path):
    corrupt = _write(tmp_path / "corrupt.pdf", b"%PDF-not-valid")
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    encrypted = tmp_path / "encrypted.pdf"
    with encrypted.open("wb") as output:
        writer.write(output)

    with pytest.raises(AttachmentRejected) as corrupt_error:
        parse_pdf(corrupt)
    with pytest.raises(AttachmentRejected) as encrypted_error:
        parse_pdf(encrypted)
    assert corrupt_error.value.code == "corrupt"
    assert encrypted_error.value.code == "encrypted"
    assert "/" not in corrupt_error.value.safe_message


def test_worker_persists_chunks_and_derivatives_before_ready(tmp_path):
    path = _write(tmp_path / "facts.txt", "关键事实：项目代号北辰。".encode())
    record = _record(path, "txt")
    repository = InMemoryAttachmentRepository()
    repository.create_receiving(replace(record, status="receiving"))
    repository.mark_stored(record.attachment_id, storage_relative_path=path.name)
    queue = InMemoryAttachmentQueue()
    queue.enqueue(record.attachment_id, record.processing_version)
    worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=tmp_path,
        parser=build_default_attachment_parser(),
        config=AttachmentWorkerConfig(parse_timeout_seconds=2),
    )

    outcome = worker.run_next()

    persisted = repository.get_parse_result(record.attachment_id, record.processing_version)
    assert outcome is not None and outcome.status == "ready"
    assert persisted is not None
    assert any("项目代号北辰" in chunk.text for chunk in persisted.chunks)
    assert repository.get(record.attachment_id).status == "ready"


def test_expired_parsed_draft_removes_original_and_all_derivatives(tmp_path):
    source = _jpeg_with_orientation(tmp_path / "expiring.jpg")
    record = replace(
        _record(source, "image"),
        expires_at=datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc),
    )
    repository = InMemoryAttachmentRepository()
    repository.create_receiving(replace(record, status="receiving"))
    repository.mark_stored(
        record.attachment_id,
        storage_relative_path=source.name,
        expires_at=record.expires_at,
    )
    queue = InMemoryAttachmentQueue()
    queue.enqueue(record.attachment_id, record.processing_version)
    worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=tmp_path,
        parser=build_default_attachment_parser(),
        config=AttachmentWorkerConfig(parse_timeout_seconds=2),
    )
    assert worker.run_next(now=record.expires_at).status == "ready"
    persisted = repository.get_parse_result(record.attachment_id, record.processing_version)
    derivative_paths = [tmp_path / item.storage_relative_path for item in persisted.derivatives]
    assert derivative_paths and all(path.exists() for path in derivative_paths)

    DraftCleaner(repository=repository, storage_root=tmp_path).cleanup(
        now=datetime(2026, 7, 13, 8, 0, 1, tzinfo=timezone.utc)
    )

    assert not source.exists()
    assert all(not path.exists() for path in derivative_paths)


def test_parse_persistence_failure_removes_uncommitted_derivative_files(tmp_path):
    class FailingPersistenceRepository(InMemoryAttachmentRepository):
        def persist_parse_result(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    source = _jpeg_with_orientation(tmp_path / "preview.jpg")
    record = _record(source, "image")
    repository = FailingPersistenceRepository()
    repository.create_receiving(replace(record, status="receiving"))
    repository.mark_stored(record.attachment_id, storage_relative_path=source.name)
    queue = InMemoryAttachmentQueue()
    queue.enqueue(record.attachment_id, record.processing_version)
    worker = AttachmentWorker(
        repository=repository,
        queue=queue,
        storage_root=tmp_path,
        parser=build_default_attachment_parser(),
        config=AttachmentWorkerConfig(parse_timeout_seconds=2),
    )

    outcome = worker.run_next()

    assert outcome is not None and outcome.status == "failed"
    derivative_root = tmp_path / "derivatives"
    assert not derivative_root.exists() or list(derivative_root.rglob("*.*")) == []


def test_visual_cache_key_includes_evidence_question_model_and_version():
    base = visual_cache_key(
        sha256="a" * 64,
        selected_locators=[{"page": 2}, {"page": 1}],
        user_question="图表说明了什么？",
        model_identity="qwen3.6",
        processing_version="attachment-v1",
    )
    reordered = visual_cache_key(
        sha256="a" * 64,
        selected_locators=[{"page": 1}, {"page": 2}],
        user_question="图表说明了什么？",
        model_identity="qwen3.6",
        processing_version="attachment-v1",
    )
    changed = visual_cache_key(
        sha256="a" * 64,
        selected_locators=[{"page": 1}, {"page": 2}],
        user_question="颜色是什么？",
        model_identity="qwen3.6",
        processing_version="attachment-v1",
    )

    assert base == reordered
    assert base != changed

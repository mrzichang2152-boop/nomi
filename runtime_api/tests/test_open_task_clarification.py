import os
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_generic_explainer_ppt_asks_goal_clarification_not_private_evidence():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "needs_clarification"
    assert result["artifact_type"] == "pptx"
    assert result["slots"]["topic"] == "AI 生成视频原理"
    assert result["slots"]["purpose"] == "讲解"
    assert result["slots"]["source_policy"] == "may_use_general_knowledge"
    assert "audience" in result["missing_required"]
    assert "depth" in result["missing_required"]
    assert "page_count" in result["defaultable"]
    assert result["requirements_contract"] is None
    assert "普通人" in result["question"]
    assert "技术" in result["question"]
    assert "未找到最近资料" not in result["question"]


def test_generic_explainer_ppt_with_audience_and_explainer_goal_is_executable():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "那你帮我做一个ppt 让普通人可以理解llm的工作原理"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["topic"] == "llm的工作原理"
    assert contract["audience"] == "普通人"
    assert contract["depth"] == "科普"
    assert contract["page_count"] == 10
    assert contract["source_policy"] == "may_use_general_knowledge"


def test_explicit_english_school_presentation_request_does_not_ask_redundant_questions():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "Create a six slide PPTX titled Solar Energy Basics for middle school students "
        "include how solar panels work components benefits limitations daily examples and a summary "
        "use a clean blue yellow visual theme and simple diagrams generate the file now without questions"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["missing_required"] == []
    contract = result["requirements_contract"]
    assert contract["topic"] == "Solar Energy Basics"
    assert contract["audience"] == "学生"
    assert contract["page_count"] == 6
    assert contract["depth"] == "科普"


def test_explicit_english_slide_contract_preserves_per_slide_titles_and_content():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "Create a 2-slide PPTX named Nomi_auto_delivery_20260720.pptx for software engineers. "
        "Slide 1 title Auto Delivery Verification subtitle No status follow-up. "
        "Slide 2 title Acceptance Result and body must include Server-side unified delivery "
        "and Android real-device received. Use concise technical depth. Do not ask questions."
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["topic"] == "Auto Delivery Verification"
    assert contract["audience"] == "技术团队"
    assert contract["page_count"] == 2
    assert contract["depth"] == "技术原理"
    assert contract["style"] == "简洁"
    assert contract["slide_outline"] == [
        {
            "slide_number": 1,
            "title": "Auto Delivery Verification",
            "subtitle": "No status follow-up",
            "must_include": [],
        },
        {
            "slide_number": 2,
            "title": "Acceptance Result",
            "subtitle": "",
            "must_include": [
                "Server-side unified delivery",
                "Android real-device received",
            ],
        },
    ]


def test_explicit_chinese_presentation_contract_preserves_title_audience_and_required_topics():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "请生成一份6页PPTX，标题为“普通人也能理解 LLM 工作原理 20260716E”。"
        "面向没有技术背景的普通人，必须讲清 token、向量表示、注意力机制、逐 token 预测、"
        "私有上下文的作用以及能力边界。使用简约工业风，生成可下载文件，不要再提问。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["topic"] == "普通人也能理解 LLM 工作原理 20260716E"
    assert contract["audience"] == "没有技术背景的普通人"
    assert contract["page_count"] == 6
    assert contract["depth"] == "科普"
    assert contract["style"] == "简约工业风"
    assert contract["must_include"] == [
        "token",
        "向量表示",
        "注意力机制",
        "逐 token 预测",
        "私有上下文的作用",
        "能力边界",
    ]


def test_english_slide_contract_strips_exact_phrase_instruction_from_required_text():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "Create a 2-slide PPTX for software engineers. "
        "Slide 1 title: Release Context Contract. Subtitle: No private retrieval. "
        "Slide 2 title: Verified Release. The body must include the exact phrases "
        "Current request retained and Irrelevant history excluded. "
        "Explain the routing decision with concise technical depth. Do not ask questions."
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["slide_outline"][1]["must_include"] == [
        "Current request retained",
        "Irrelevant history excluded",
    ]
    assert contract["must_include"] == [
        "Release Context Contract",
        "No private retrieval",
        "Verified Release",
        "Current request retained",
        "Irrelevant history excluded",
    ]


def test_management_review_presentation_infers_business_depth_without_redundant_clarification():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "请生成一份4页中文PPTX，主题是“Q2客户支持复盘”，用于给公司管理层汇报。"
        "四页依次为：结论摘要、关键指标、观察与风险、待评估行动。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["audience"] == "管理层"
    assert contract["page_count"] == 4
    assert contract["depth"] == "业务复盘"


def test_management_review_presentation_preserves_bracketed_title_and_inline_evidence_policy():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "请生成一份4页PPTX《Q2客户支持复盘汇报》，受众是管理层，用于15分钟复盘。"
        "数据来源仅限以下明确事实：首次响应时间12分钟、平均解决时长4.2小时、升级率0.9%、"
        "夜间响应更慢但原因未知。第1页标题与结论摘要；第2页展示上述四项指标，其中原因未知必须明确标注未知；"
        "第3页总结现状与证据；第4页列出三项待评估行动：优化夜间排班、建立升级预警、每周复盘。"
        "不得编造其他数据，使用原生可编辑图形，版式清晰。"
    )
    payload = build_artifact_task_payload(
        message,
        source_context=[],
        memory_context=[],
        current_request_evidence_id="event-current-request",
    )

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["topic"] == "Q2客户支持复盘汇报"
    assert contract["audience"] == "管理层"
    assert contract["page_count"] == 4
    assert contract["depth"] == "业务复盘"
    assert contract["source_policy"] == "must_use_private_evidence"
    assert contract["must_include"] == [
        "标题与结论摘要",
        "展示上述四项指标，其中原因未知必须明确标注未知",
        "总结现状与证据",
        "列出三项待评估行动：优化夜间排班、建立升级预警、每周复盘",
    ]
    assert contract["assumptions"] == []


def test_presentation_topic_uses_the_business_subject_instead_of_format_descriptors():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "生成一份4页中文PPT，用于给公司管理层做Q2客户支持复盘汇报，"
        "面向公司管理层，内容偏业务复盘。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["requirements_contract"]["topic"] == "Q2客户支持复盘"


def test_presentation_clarification_only_asks_for_the_field_that_is_actually_missing():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "生成4页PPTX，主题是销售漏斗，面向管理层"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "needs_clarification"
    assert result["missing_required"] == ["depth"]
    assert "偏业务总结、科普讲解，还是技术原理" in result["question"]
    assert "讲给普通人、学生、客户" not in result["question"]
    assert "10 页" not in result["question"]


def test_private_evidence_ppt_requires_source_material_before_execution():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "帮我依据刚刚王总给的资料做一份 PPT"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "needs_clarification"
    assert result["slots"]["source_policy"] == "must_use_private_evidence"
    assert "source_material" in result["missing_required"]
    assert "王总" in result["question"]
    assert "资料" in result["question"]
    assert result["requirements_contract"] is None


def test_follow_up_answer_merges_slots_and_creates_requirements_contract():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    original = "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解"
    payload = build_artifact_task_payload(original, source_context=[], memory_context=[])
    pending = analyze_open_task_clarity(original, artifact_payload=payload)

    result = analyze_open_task_clarity(
        "普通人，10页，偏科普，可以多用类比",
        artifact_payload=payload,
        pending_task_state=pending,
    )

    assert result["status"] == "executable"
    assert result["missing_required"] == []
    contract = result["requirements_contract"]
    assert contract["deliverable"] == "pptx"
    assert contract["audience"] == "普通人"
    assert contract["page_count"] == 10
    assert contract["depth"] == "科普"
    assert contract["source_policy"] == "may_use_general_knowledge"
    assert "AI 生成视频原理" in contract["final_goal"]
    assert "用户未提供私有资料" in " ".join(contract["assumptions"])


def test_english_follow_up_answer_merges_slots_and_creates_requirements_contract():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    original = "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解"
    payload = build_artifact_task_payload(original, source_context=[], memory_context=[])
    pending = analyze_open_task_clarity(original, artifact_payload=payload)

    result = analyze_open_task_clarity(
        "ordinary people, 10 pages, popular science style, use analogies",
        artifact_payload=payload,
        pending_task_state=pending,
    )

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["audience"] == "普通人"
    assert contract["page_count"] == 10
    assert contract["depth"] == "科普"
    assert contract["style"] == "多用类比"


def test_english_manager_verification_follow_up_preserves_explicit_slide_count_and_proceeds():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    original = (
        "Create a 2-slide PPTX titled Android verification. "
        "Slide 1: title. Slide 2: latency 2 seconds and status available. "
        "Do not invent data."
    )
    payload = build_artifact_task_payload(original, source_context=[], memory_context=[])
    pending = analyze_open_task_clarity(original, artifact_payload=payload)

    assert pending["status"] == "needs_clarification"
    assert pending["slots"]["page_count"] == 2
    assert pending["slots"]["source_policy"] == "must_use_private_evidence"
    assert pending["slots"]["must_include"] == [
        "latency 2 seconds and status available"
    ]
    assert "10 页" not in pending["question"]

    result = analyze_open_task_clarity(
        "Audience is managers. Purpose is a 2-minute system verification. "
        "Exactly 2 slides. Proceed now.",
        artifact_payload=payload,
        pending_task_state=pending,
    )

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["audience"] == "管理层"
    assert contract["purpose"] == "2-minute system verification"
    assert contract["page_count"] == 2
    assert contract["depth"] == "业务总结"
    assert contract["source_policy"] == "must_use_private_evidence"
    assert contract["must_include"] == [
        "latency 2 seconds and status available"
    ]
    assert "10 页" not in " ".join(contract["assumptions"])


def test_user_can_choose_safe_defaults_for_generic_ppt():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    original = "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解"
    payload = build_artifact_task_payload(original, source_context=[], memory_context=[])
    pending = analyze_open_task_clarity(original, artifact_payload=payload)

    result = analyze_open_task_clarity("按默认做", artifact_payload=payload, pending_task_state=pending)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["audience"] == "普通人"
    assert contract["page_count"] == 10
    assert contract["depth"] == "科普"
    assert "普通人听众、10 页、科普风" in " ".join(contract["assumptions"])


def test_spreadsheet_request_builds_field_and_calculation_contract():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "做一个用于核算项目利润的 Excel 表格，字段包括项目、收入、成本，计算利润和利润率"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["deliverable"] == "xlsx"
    assert contract["purpose"] == "核算项目利润"
    assert contract["columns"] == ["项目", "收入", "成本"]
    assert contract["calculations"] == ["利润", "利润率"]
    assert contract["must_not_invent_missing_values"] is True


def test_spreadsheet_request_preserves_explicit_formula_rules_and_inline_data_source():
    from app.artifact_tasks import build_artifact_task_payload, filtered_missing_evidence_from_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "生成XLSX用于分析项目利润，字段包括项目、收入、成本、利润、利润率；"
        "数据为Alpha收入128000成本83000；利润必须用收入减成本的公式，"
        "利润率必须用利润除以收入的公式。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["requirements_contract"]["calculations"] == [
        "利润必须用收入减成本的公式",
        "利润率必须用利润除以收入的公式",
    ]
    payload["requirements_contract"] = result["requirements_contract"]
    assert "数据来源" not in filtered_missing_evidence_from_payload(payload)


def test_document_request_builds_audience_and_section_contract():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "写一份面向管理层的项目复盘 Word 报告，用于汇报，章节包括执行摘要、问题分析、行动计划"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["deliverable"] == "docx"
    assert contract["audience"] == "管理层"
    assert contract["purpose"] == "汇报"
    assert contract["sections"] == ["执行摘要", "问题分析", "行动计划"]
    assert contract["native_editable_content"] is True


def test_document_audience_does_not_absorb_the_output_format_or_title():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "生成一份面向公司管理层的中文DOCX报告，用于Q2客户支持复盘汇报。"
        "章节包括执行摘要、事实观察、待评估行动。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["requirements_contract"]["audience"] == "管理层"


def test_image_phrase_has_evidence_does_not_force_private_evidence_policy():
    from app.artifact_tasks import build_artifact_task_payload, filtered_missing_evidence_from_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = (
        "生成一张中文PNG信息图，用于向产品经理解释流程，面向非技术产品经理。"
        "只表达三个有依据的阶段，不要声称绝对安全。"
    )
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["requirements_contract"]["source_policy"] == "may_use_general_knowledge"
    payload["requirements_contract"] = result["requirements_contract"]
    assert "画布尺寸" not in filtered_missing_evidence_from_payload(payload)


def test_image_request_builds_visual_and_canvas_contract():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    message = "生成一张面向普通人的 RAG 流程信息图，用于培训，横版 1600x1000"
    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    contract = result["requirements_contract"]
    assert contract["deliverable"] == "image"
    assert contract["audience"] == "普通人"
    assert contract["purpose"] == "培训"
    assert contract["visual_kind"] == "infographic"
    assert contract["canvas"] == {"width": 1600, "height": 1000, "orientation": "landscape"}
    assert contract["output_format"] == "png"


@pytest.mark.parametrize(
    ("message", "expected_deliverable", "expected_topic"),
    [
        (
            "生成一份 XLSX，标题为“季度经营数据 20260716”。用于经营分析，字段包括季度、收入、成本，计算利润和利润率。",
            "xlsx",
            "季度经营数据 20260716",
        ),
        (
            "生成一份 DOCX，标题为“项目复盘报告 20260716”。面向管理层，用于汇报，章节包括执行摘要、问题分析、行动计划。",
            "docx",
            "项目复盘报告 20260716",
        ),
        (
            "生成一张 PNG 信息图，标题为“RAG 工作流程 20260716”。面向普通人，用于培训，横版 1600x1000。",
            "image",
            "RAG 工作流程 20260716",
        ),
    ],
)
def test_explicit_chinese_title_is_used_for_every_artifact_contract(
    message: str,
    expected_deliverable: str,
    expected_topic: str,
):
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    payload = build_artifact_task_payload(message, source_context=[], memory_context=[])

    result = analyze_open_task_clarity(message, artifact_payload=payload)

    assert result["status"] == "executable"
    assert result["requirements_contract"]["deliverable"] == expected_deliverable
    assert result["requirements_contract"]["topic"] == expected_topic


def test_unclear_non_presentation_tasks_ask_format_specific_questions():
    from app.artifact_tasks import build_artifact_task_payload
    from app.open_task_clarification import analyze_open_task_clarity

    cases = [
        ("帮我做一个 Excel 表格", ["purpose", "columns"], "字段"),
        ("帮我写一份 Word 文档", ["purpose", "audience"], "读者"),
        ("帮我生成一张信息图", ["purpose", "audience"], "受众"),
    ]
    for message, expected_missing, question_term in cases:
        payload = build_artifact_task_payload(message, source_context=[], memory_context=[])
        result = analyze_open_task_clarity(message, artifact_payload=payload)
        assert result["status"] == "needs_clarification"
        assert all(item in result["missing_required"] for item in expected_missing)
        assert question_term in result["question"]

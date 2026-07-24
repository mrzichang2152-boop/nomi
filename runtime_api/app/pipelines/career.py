from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlparse

from app.pipelines.base import pipeline_result


OWNED_PIPELINES = {
    "career_profile_pipeline",
    "job_discovery_pipeline",
    "job_recommendation_pipeline",
    "job_fit_scoring_pipeline",
    "resume_tailoring_pipeline",
    "cover_letter_pipeline",
    "outreach_message_pipeline",
    "job_application_pipeline",
    "application_tracking_pipeline",
    "interview_prep_pipeline",
    "linkedin_contact_search_pipeline",
}


def run_career_pipeline(pipeline_id: str, request: str, context: dict[str, Any]) -> dict[str, Any] | None:
    context = context or {}
    if pipeline_id not in OWNED_PIPELINES:
        return None
    if pipeline_id == "career_profile_pipeline":
        return _career_profile_pipeline(request, context)
    if pipeline_id == "job_discovery_pipeline":
        return _job_discovery_pipeline(request, context)
    if pipeline_id == "job_recommendation_pipeline":
        return _job_recommendation_pipeline(request, context)
    if pipeline_id == "job_fit_scoring_pipeline":
        return _job_fit_scoring_pipeline(request, context)
    if pipeline_id == "resume_tailoring_pipeline":
        return _resume_tailoring_pipeline(request, context)
    if pipeline_id == "cover_letter_pipeline":
        return _cover_letter_pipeline(request, context)
    if pipeline_id == "outreach_message_pipeline":
        return _outreach_message_pipeline(request, context)
    if pipeline_id == "job_application_pipeline":
        return _job_application_pipeline(request, context)
    if pipeline_id == "application_tracking_pipeline":
        return _application_tracking_pipeline(request, context)
    if pipeline_id == "interview_prep_pipeline":
        return _interview_prep_pipeline(request, context)
    if pipeline_id == "linkedin_contact_search_pipeline":
        return _linkedin_contact_search_pipeline(request, context)
    return None


def _career_profile_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    resume = _resume(context)
    profile = _career_profile(context)
    skills = _ordered_unique([*profile.get("skills", []), *_resume_skills(resume)])
    target_roles = _target_roles(request, context, resume, profile)
    resolved = {"profile_source": "resume_or_private_memory"} if resume or profile else {}
    status = "completed_read_only" if resolved else "needs_user_input"
    return pipeline_result(
        pipeline_id="career_profile_pipeline",
        status=status,
        required_slots=["profile_source"],
        resolved_slots=resolved,
        permission="read_only",
        steps=["读取简历和求职上下文", "抽取技能和目标", "生成职业画像", "记录证据"],
        output={
            "career_profile": {
                "career_profile_id": profile.get("career_profile_id") or "career_profile_default",
                "headline": profile.get("headline") or resume.get("headline") or "",
                "target_roles": [role for role in target_roles if role],
                "target_locations": _as_list(profile.get("target_locations")),
                "skills": skills,
                "evidence_ids": _evidence_ids(context, resume),
            },
            "unsupported_claims": [],
        },
        writeback_targets=["memory_items", "knowledge_entities", "task_trace"],
        writeback_plan=[
            {
                "target": "memory_items",
                "operation": "upsert_career_profile",
                "payload": {"skills": skills, "target_roles": [role for role in target_roles if role]},
            }
        ],
    )


def _job_discovery_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    jobs = _jobs(context)
    if not jobs:
        jobs = _jobs_from_pages(context)
    if not jobs:
        jobs = _jobs_from_web_context(context)
    if not jobs:
        job = _job(context)
        if job:
            jobs = [job]
    query = str(context.get("query") or _extract_job_query(request) or "").strip()
    resolved = {"query": query} if query else {}
    if jobs:
        resolved["source"] = str(jobs[0].get("source") or context.get("source") or "manual")
    normalized = [_normalize_job(job, index=index) for index, job in enumerate(jobs)]
    linkedin_job_search = _linkedin_job_search_request(request, context)
    needs_linkedin_search = bool(query and not normalized and linkedin_job_search.get("command"))
    if normalized:
        status = "completed_read_only"
    elif needs_linkedin_search:
        status = "ready_for_browser_navigation"
    elif query:
        status = "completed_read_only"
    else:
        status = "needs_user_input"
    output = {
        "query": query,
        "job_opportunities": normalized,
        "source_adapters": [
            "greenhouse_public",
            "lever_public",
            "ashby_public",
            "workable_public",
            "smartrecruiters_public",
            "linkedin_browser_observation",
            "gmail_recruiter_signal",
        ],
        "next_actions": ["匹配简历", "生成外联草稿", "加入机会跟踪"],
    }
    provider_calls: list[dict[str, Any]] = []
    writeback_plan = [
        {"target": "job_opportunities", "operation": "upsert", "payload": item}
        for item in normalized
    ]
    if needs_linkedin_search:
        output["linkedin_job_search"] = linkedin_job_search
        output["next_actions"] = ["等待 LinkedIn 搜索页采集岗位", "匹配简历", "生成推荐卡"]
        provider_calls.append(
            {
                "provider": "managed_browser",
                "action": "browser.open_linkedin_job_search",
                "status": "planned",
                "external_side_effect": False,
                "url": linkedin_job_search["target_url"],
                "command": linkedin_job_search["command"],
            }
        )
        writeback_plan.append(
            {
                "target": "task_trace",
                "operation": "append_browser_navigation_plan",
                "payload": {
                    "source": "linkedin",
                    "target_url": linkedin_job_search["target_url"],
                    "expected_event_type": "linkedin_job_search_results",
                    "source_event_ids": _as_list(context.get("source_event_ids")),
                },
            }
        )
    return pipeline_result(
        pipeline_id="job_discovery_pipeline",
        status=status,
        required_slots=["query"],
        resolved_slots=resolved,
        permission="read_only",
        steps=["解析求职目标", "读取候选来源", "规范化岗位", "输出机会列表"],
        output=output,
        provider_calls=provider_calls,
        writeback_targets=["job_opportunities", "task_trace", "memory_items"],
        writeback_plan=writeback_plan,
    )


def _job_fit_scoring_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id")})
    missing = [slot for slot in ["job_id", "resume_id"] if not resolved.get(slot)]
    if missing:
        return pipeline_result(
            pipeline_id="job_fit_scoring_pipeline",
            status="needs_user_input",
            required_slots=["job_id", "resume_id"],
            resolved_slots=resolved,
            permission="read_only",
            steps=["读取 JD", "读取简历", "匹配要求", "输出评分"],
            output={"question": "需要岗位 JD 和用户简历后才能做匹配评分。"},
            writeback_targets=["task_trace"],
        )
    matched, gaps = _match_requirements(job, resume)
    jd_requirements = _job_requirements(job)
    denominator = max(len(jd_requirements), 1)
    score = min(1.0, round((len(matched) / denominator) * 0.82 + _role_bonus(job, resume), 2))
    return pipeline_result(
        pipeline_id="job_fit_scoring_pipeline",
        status="completed_read_only",
        required_slots=["job_id", "resume_id"],
        resolved_slots=resolved,
        permission="read_only",
        steps=["读取 JD", "读取简历", "匹配要求", "输出评分"],
        output={
            "fit_score": score,
            "matched_requirements": matched,
            "gaps": gaps,
            "recommendation": "值得申请" if score >= 0.65 else "先补材料再申请",
            "evidence_ids": _evidence_ids(context, resume),
            "unsupported_claims": [],
        },
        writeback_targets=["job_opportunities", "memory_items", "task_trace"],
        writeback_plan=[
            {
                "target": "job_opportunities",
                "operation": "update_fit_score",
                "payload": {"job_id": job.get("job_id"), "fit_score": score, "matched_requirements": matched, "gaps": gaps},
            }
        ],
    )


def _job_recommendation_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    resume = _resume(context)
    profile = _career_profile(context)
    effective_resume = _effective_resume_for_matching(resume, profile)
    jobs = [_normalize_job(job, index=index) for index, job in enumerate(_jobs(context) or _jobs_from_pages(context))]
    resolved = _compact(
        {
            "resume_id": resume.get("resume_id") or effective_resume.get("resume_id"),
            "career_profile_id": profile.get("career_profile_id") or profile.get("id"),
            "candidate_count": len(jobs) if jobs else None,
        }
    )
    if not effective_resume or not (resume.get("resume_id") or effective_resume.get("resume_id")):
        return pipeline_result(
            pipeline_id="job_recommendation_pipeline",
            status="needs_user_input",
            required_slots=["resume_id"],
            resolved_slots=resolved,
            permission="read_only",
            steps=["读取简历和职业画像", "汇总候选 JD", "批量匹配评分", "生成对话推荐卡"],
            output={"question": "需要先导入或选择一份基础简历，才能判断哪些岗位真正适合你。"},
            writeback_targets=["task_trace"],
        )
    if not jobs:
        linkedin_job_search = _linkedin_job_search_request(request, context)
        provider_calls = []
        writeback_plan = []
        if linkedin_job_search.get("command"):
            provider_calls.append(
                {
                    "provider": "managed_browser",
                    "action": "browser.open_linkedin_job_search",
                    "status": "planned",
                    "external_side_effect": False,
                    "url": linkedin_job_search["target_url"],
                    "command": linkedin_job_search["command"],
                }
            )
            writeback_plan.append(
                {
                    "target": "task_trace",
                    "operation": "append_browser_navigation_plan",
                    "payload": {
                        "source": "linkedin",
                        "target_url": linkedin_job_search["target_url"],
                        "expected_event_type": "linkedin_job_search_results",
                        "source_event_ids": _as_list(context.get("source_event_ids")),
                    },
                }
            )
        return pipeline_result(
            pipeline_id="job_recommendation_pipeline",
            status="needs_candidate_jobs" if linkedin_job_search.get("command") else "no_recommendable_jobs",
            required_slots=["resume_id"],
            resolved_slots=resolved,
            permission="read_only",
            steps=["读取简历和职业画像", "汇总候选 JD", "批量匹配评分", "生成对话推荐卡"],
            output={
                "job_recommendations": [],
                "summary": "没有可用于筛选的 JD。已准备打开 LinkedIn Jobs 搜索页，采集到岗位后再按简历/画像筛选推荐。"
                if linkedin_job_search.get("command")
                else "没有可用于筛选的 JD。可以连接 LinkedIn、打开公司招聘页，或给 Nomi 一个目标岗位/公司。",
                **({"linkedin_job_search": linkedin_job_search} if linkedin_job_search.get("command") else {}),
            },
            provider_calls=provider_calls,
            writeback_targets=["task_trace"],
            writeback_plan=writeback_plan,
            validation_warnings=["no_candidate_jobs"],
        )
    scored = [_score_job_recommendation(job, effective_resume, profile) for job in jobs]
    visible = [
        item
        for item in sorted(scored, key=lambda row: row["fit_score"], reverse=True)
        if item["recommendation_tier"] in {"strong_fit", "good_fit"}
    ][: int(context.get("recommendation_limit") or 5)]
    if not visible:
        return pipeline_result(
            pipeline_id="job_recommendation_pipeline",
            status="low_confidence_results",
            required_slots=["resume_id"],
            resolved_slots=resolved,
            permission="read_only",
            steps=["读取简历和职业画像", "汇总候选 JD", "批量匹配评分", "生成对话推荐卡"],
            output={
                "job_recommendations": [],
                "low_confidence_results": scored[:5],
                "summary": "候选岗位与当前简历匹配度都不高，因此不会主动推送给你。",
            },
            writeback_targets=["job_opportunities", "task_trace"],
            writeback_plan=[
                {"target": "job_opportunities", "operation": "upsert_recommendation_score", "payload": _job_writeback_payload(item)}
                for item in scored
            ],
            validation_warnings=["no_good_fit_recommendations"],
        )

    suggestion = _job_recommendation_suggestion_payload(visible, context)
    writeback_plan = [
        {"target": "job_opportunities", "operation": "upsert_recommendation_score", "payload": _job_writeback_payload(item)}
        for item in scored
    ]
    writeback_plan.append({"target": "proactive_suggestions", "operation": "create", "payload": suggestion})
    return pipeline_result(
        pipeline_id="job_recommendation_pipeline",
        status="completed_read_only",
        required_slots=["resume_id"],
        resolved_slots=resolved,
        permission="read_only",
        steps=["读取简历和职业画像", "汇总候选 JD", "批量匹配评分", "生成对话推荐卡"],
        output={
            "job_recommendations": visible,
            "summary": _job_recommendation_summary(visible),
            "next_actions": ["查看JD", "加入求职看板", "改简历", "联系HR", "忽略"],
        },
        writeback_targets=["job_opportunities", "proactive_suggestions", "assistant_turns", "task_trace"],
        writeback_plan=writeback_plan,
    )


def _resume_tailoring_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id")})
    matched, gaps = _match_requirements(job, resume)
    status = "draft_ready" if not _missing(resolved, ["job_id", "resume_id"]) else "needs_user_input"
    changes = [
        {
            "section": "summary",
            "change": f"突出与 {job.get('title') or '目标岗位'} 相关的 {', '.join(matched[:3])}。",
            "evidence_ids": _evidence_ids(context, resume),
        }
    ]
    if gaps:
        changes.append(
            {
                "section": "skills_or_projects",
                "change": f"不要编造经历；把 {', '.join(gaps[:3])} 标为待补充或需要用户确认。",
                "evidence_ids": [],
            }
        )
    return pipeline_result(
        pipeline_id="resume_tailoring_pipeline",
        status=status,
        required_slots=["job_id", "resume_id"],
        resolved_slots=resolved,
        permission="draft",
        steps=["读取 JD", "读取基础简历", "生成修改草案", "检查无证据声明"],
        output={
            "resume_version_plan": {
                "base_resume_id": resume.get("resume_id"),
                "target_job_id": job.get("job_id"),
                "changes": changes,
            },
            "unsupported_claims": [],
            "write_blocked": True,
        },
        writeback_targets=["resume_versions", "task_trace"],
        writeback_plan=[
            {
                "target": "resume_versions",
                "operation": "draft",
                "payload": {"base_resume_id": resume.get("resume_id"), "target_job_id": job.get("job_id"), "changes": changes},
            }
        ] if status == "draft_ready" else [],
    )


def _cover_letter_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    recipient = str(context.get("recipient") or "Hiring Team")
    channel = str(context.get("channel") or "gmail")
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id")})
    status = "draft_ready" if not _missing(resolved, ["job_id", "resume_id"]) else "needs_user_input"
    matched, _ = _match_requirements(job, resume)
    display_skills = _cover_letter_display_skills(job, resume, matched)
    resume_highlights = _cover_letter_resume_highlights(resume, display_skills)
    body = (
        f"Hi {recipient},\n\n"
        f"I am interested in the {job.get('title') or 'open'} role at {job.get('company') or 'your team'}. "
        f"My background is strongest in {', '.join(display_skills[:3]) or resume.get('headline') or 'relevant product work'}, "
        f"and my recent work includes {resume_highlights}.\n\n"
        "I would be glad to share more context and discuss whether this role is a fit.\n\n"
        "Best,\nNomi"
    )
    return pipeline_result(
        pipeline_id="cover_letter_pipeline",
        status=status,
        required_slots=["job_id", "resume_id"],
        resolved_slots=resolved,
        permission="draft",
        steps=["读取 JD", "读取简历", "生成草稿", "检查证据"],
        output={
            "draft": {
                "channel": channel,
                "recipient": recipient,
                "subject": f"Application interest - {job.get('title') or 'Role'} at {job.get('company') or 'Company'}",
                "body": body,
                "evidence_ids": _evidence_ids(context, resume),
            },
            "unsupported_claims": [],
            "send_blocked": True,
        },
        writeback_targets=["assistant_turns", "task_trace"],
    )


def _outreach_message_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    contact = _contact(context)
    channel = str(contact.get("channel") or context.get("channel") or "linkedin")
    recipient = str(contact.get("name") or context.get("recipient") or "")
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id"), "recipient": recipient, "channel": channel})
    status = "draft_ready" if not _missing(resolved, ["job_id", "resume_id", "recipient", "channel"]) else "needs_user_input"
    matched, _ = _match_requirements(job, resume)
    body = (
        f"Hi {recipient}, I noticed the {job.get('title') or 'role'} opening at {job.get('company') or 'your team'}. "
        f"My recent work is closely related to {', '.join(matched[:2]) or resume.get('headline') or 'the role requirements'}. "
        "Would it be okay if I shared a short background and asked one or two questions about the role?"
    )
    return pipeline_result(
        pipeline_id="outreach_message_pipeline",
        status=status,
        required_slots=["job_id", "resume_id", "recipient", "channel"],
        resolved_slots=resolved,
        permission="external_message",
        steps=["识别联系人", "读取 JD 与简历", "生成外联草稿", "阻断直接发送"],
        output={
            "draft": {
                "channel": channel,
                "recipient": recipient,
                "body": body,
                "evidence_ids": _evidence_ids(context, resume, extra=_as_list(context.get("source_event_ids"))),
            },
            "confirmation_card": {
                "kind": "career_outreach_message",
                "message": "发送前需要用户确认；Nomi 不会直接发送 LinkedIn/Gmail/WhatsApp 消息。",
                "confirm_action": "send_message",
                "final_user_confirmation": True,
            },
            "unsupported_claims": [],
        },
        writeback_targets=["assistant_turns", "task_trace", "memory_items"],
        external_effects=["send_message"],
        writeback_plan=[
            {
                "target": "assistant_turns",
                "operation": "draft_external_message",
                "payload": {"recipient": recipient, "channel": channel, "target_job_id": job.get("job_id")},
            }
        ] if status == "draft_ready" else [],
    )


def _job_application_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    action = str(context.get("application_action") or _application_action(request) or "prepare_application")
    platform = _platform_for_job(job)
    target_id = f"apply_{job.get('job_id') or 'unknown'}"
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id"), "application_action": action})
    missing = _missing(resolved, ["job_id", "resume_id", "application_action"])
    has_grant = bool(context.get("delegated_grant") or context.get("grant_id"))
    has_manifest = bool(context.get("target_manifest") or context.get("manifest_id"))
    status = "ready_for_confirmation" if not missing and has_grant and has_manifest else "blocked_until_delegated_grant"
    suggested_grant = {
        "scenario": "job_agent",
        "platform": platform,
        "surface": "cloud_playwright_browser",
        "action": action,
        "automation_level": "L4",
        "daily_limit": min(int(context.get("daily_limit") or 10), 20),
        "batch_limit": min(int(context.get("batch_limit") or 5), 10),
        "requires_target_manifest": True,
        "requires_grounded_content": True,
        "stop_on_challenge": True,
        "stop_on_user_pause": True,
    }
    suggested_manifest = {
        "scenario": "job_agent",
        "platform": platform,
        "action": action,
        "targets": [
            {
                "target_id": target_id,
                "target_type": "job_application",
                "name": job.get("title") or "Unknown role",
                "company": job.get("company") or "",
                "profile_url": job.get("url") or "",
                "related_job_id": job.get("job_id") or "",
                "draft_id": resume.get("resume_id") or "",
                "risk": "high",
            }
        ],
        "max_actions": 1,
        "created_from_evidence_ids": _evidence_ids(context, resume),
    }
    return pipeline_result(
        pipeline_id="job_application_pipeline",
        status=status,
        required_slots=["job_id", "resume_id", "application_action"],
        resolved_slots=resolved,
        permission="external_execution",
        steps=["准备申请材料", "检查授权", "生成目标清单", "阻断未授权提交"],
        output={
            "apply_submit_blocked": status == "blocked_until_delegated_grant",
            "automation_requirements": {
                "requires_target_manifest": True,
                "requires_grounded_content": True,
                "requires_quota": True,
                "stop_on_challenge": True,
            },
            "suggested_grant": suggested_grant,
            "suggested_manifest": suggested_manifest,
            "confirmation_card": {
                "kind": "job_application_submit",
                "message": "Apply/Submit 属于外部执行动作；缺少授权、目标清单或证据时必须阻断。",
                "confirm_action": action,
                "final_user_confirmation": True,
            },
        },
        writeback_targets=["task_trace", "job_applications", "delegated_automation_grants", "delegated_automation_manifests"],
        external_effects=[action],
        writeback_plan=[
            {
                "target": "job_applications",
                "operation": "upsert_application_intent",
                "payload": {
                    "job_id": job.get("job_id"),
                    "resume_id": resume.get("resume_id"),
                    "status": status,
                    "stage": "apply_submit_blocked" if status == "blocked_until_delegated_grant" else "ready_for_user_confirmation",
                    "next_step": "request_delegated_grant_and_target_manifest"
                    if status == "blocked_until_delegated_grant"
                    else "wait_for_final_user_confirmation",
                    "application_action": action,
                    "platform": platform,
                    "source_event_ids": _evidence_ids(context, resume),
                },
            },
            {"target": "delegated_automation_grants", "operation": "suggest", "payload": suggested_grant},
            {"target": "delegated_automation_manifests", "operation": "suggest", "payload": suggested_manifest},
        ],
    )


def _application_tracking_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    stage = str(context.get("stage") or context.get("status") or "interested")
    next_step = str(context.get("next_step") or "review_fit_and_prepare_materials")
    resolved = _compact({"job_id": job.get("job_id"), "stage": stage})
    return pipeline_result(
        pipeline_id="application_tracking_pipeline",
        status="completed_read_only" if job.get("job_id") else "needs_user_input",
        required_slots=["job_id", "stage"],
        resolved_slots=resolved,
        permission="write",
        steps=["读取机会", "更新阶段", "记录下一步", "安排跟进"],
        output={"application_state": {"job_id": job.get("job_id"), "stage": stage, "next_step": next_step}},
        writeback_targets=["job_applications", "agenda_items", "task_trace"],
        writeback_plan=[
            {"target": "job_applications", "operation": "upsert_stage", "payload": {"job_id": job.get("job_id"), "stage": stage, "next_step": next_step}}
        ] if job.get("job_id") else [],
    )


def _interview_prep_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(_job(context))
    resume = _resume(context)
    matched, gaps = _match_requirements(job, resume)
    resolved = _compact({"job_id": job.get("job_id"), "resume_id": resume.get("resume_id")})
    return pipeline_result(
        pipeline_id="interview_prep_pipeline",
        status="completed_read_only" if not _missing(resolved, ["job_id", "resume_id"]) else "needs_user_input",
        required_slots=["job_id", "resume_id"],
        resolved_slots=resolved,
        permission="read_only",
        steps=["读取 JD", "读取简历", "生成问题", "生成回答素材"],
        output={
            "prep_brief": {
                "role": job.get("title") or "",
                "company": job.get("company") or "",
                "talking_points": matched[:5],
                "risk_questions": [f"如何补充或解释 {gap} 相关经验？" for gap in gaps[:5]],
                "evidence_ids": _evidence_ids(context, resume),
            }
        },
        writeback_targets=["assistant_turns", "task_trace"],
    )


def _clean_search_term(value: str, max_length: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    cleaned = re.sub(r"[<>\"`{}\\]", "", cleaned)
    return cleaned[:max_length].strip()


GENERIC_JOB_SEARCH_QUERIES = {
    "帮我找找看有没有适合我的工作机会",
    "找找看有没有适合我的工作机会",
    "有没有适合我的工作机会",
    "适合我的工作机会",
    "工作机会",
    "招聘信息",
}


def _linkedin_job_search_terms(request: str, context: dict[str, Any]) -> dict[str, str]:
    resume = _resume(context)
    profile = _career_profile(context)
    explicit_query = _clean_search_term(str(context.get("query") or context.get("job_title") or context.get("role") or ""))
    extracted_query = _clean_search_term(_extract_job_query(request))
    if extracted_query in GENERIC_JOB_SEARCH_QUERIES or len(extracted_query) > 80:
        extracted_query = ""
    role_candidates = _ordered_unique(
        [
            explicit_query,
            extracted_query,
            *_as_list(profile.get("target_roles")),
            *_as_list(resume.get("target_roles")),
            str(resume.get("target_role") or ""),
            str(profile.get("headline") or ""),
            str(resume.get("headline") or ""),
        ]
    )
    query = ""
    for candidate in role_candidates:
        normalized = _clean_search_term(_normalize_role_text(candidate), max_length=220)
        if normalized and normalized not in GENERIC_JOB_SEARCH_QUERIES:
            query = normalized
            break
    location_candidates = _ordered_unique(
        [
            str(context.get("location") or ""),
            *_as_list(profile.get("target_locations")),
            *_as_list(resume.get("target_locations")),
            str(resume.get("target_location") or ""),
        ]
    )
    location = ""
    for candidate in location_candidates:
        normalized_location = _clean_search_term(candidate, max_length=120)
        if normalized_location:
            location = normalized_location
            break
    return {"query": query, "location": location}


def _linkedin_job_search_url(search_terms: dict[str, str]) -> tuple[str, str]:
    query = _clean_search_term(str(search_terms.get("query") or ""), max_length=220)
    location = _clean_search_term(str(search_terms.get("location") or ""), max_length=120)
    params = {"keywords": query}
    if location:
        params["location"] = location
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params), " ".join(item for item in [query, location] if item)


def _linkedin_job_search_request(request: str, context: dict[str, Any]) -> dict[str, Any]:
    search_terms = _linkedin_job_search_terms(request, context)
    if not search_terms.get("query"):
        return {}
    search_url, keywords = _linkedin_job_search_url(search_terms)
    command = {
        "action": "open_linkedin_job_search",
        "source": "linkedin",
        "url": search_url,
        "host_fragment": "linkedin.com",
        "query": search_terms["query"],
        "location": search_terms["location"],
        "expected_event_type": "linkedin_job_search_results",
    }
    return {
        "source": "linkedin",
        "search_terms": search_terms,
        "keywords": keywords,
        "target_url": search_url,
        "expected_event_type": "linkedin_job_search_results",
        "command": command,
        "safety": {
            "read_only": True,
            "external_side_effect": False,
            "blocked_actions": ["connect", "message", "apply", "submit"],
        },
    }


def _linkedin_contact_search_terms(request: str, context: dict[str, Any]) -> dict[str, str]:
    job = _normalize_job(_job(context))
    company = _clean_search_term(str(context.get("company") or job.get("company") or ""))
    job_title = _clean_search_term(str(context.get("job_title") or context.get("role") or job.get("title") or _extract_job_query(request)))
    location = _clean_search_term(str(context.get("location") or job.get("location") or ""), max_length=120)
    return {"company": company, "job_title": job_title, "location": location}


def _linkedin_contact_search_url(search_terms: dict[str, str]) -> tuple[str, str]:
    keywords = " ".join(
        item
        for item in [
            search_terms.get("company") or "",
            search_terms.get("job_title") or "",
            search_terms.get("location") or "",
            "recruiter",
            "talent acquisition",
            "hiring manager",
            "HR",
        ]
        if item
    )
    return "https://www.linkedin.com/search/results/people/?" + urlencode({"keywords": keywords[:500]}), keywords


def _linkedin_contact_search_pipeline(request: str, context: dict[str, Any]) -> dict[str, Any]:
    search_terms = _linkedin_contact_search_terms(request, context)
    resolved = _compact(search_terms)
    required = ["company", "job_title"]
    status = "ready_for_browser_navigation" if not _missing(resolved, required) else "needs_user_input"
    search_url, keywords = _linkedin_contact_search_url(search_terms)
    command = {
        "action": "open_linkedin_contact_search",
        "source": "linkedin",
        "url": search_url,
        "host_fragment": "linkedin.com",
        "company": search_terms["company"],
        "job_title": search_terms["job_title"],
        "location": search_terms["location"],
        "expected_event_type": "linkedin_contact_snapshot",
    }
    return pipeline_result(
        pipeline_id="linkedin_contact_search_pipeline",
        status=status,
        required_slots=required,
        resolved_slots=resolved,
        permission="read_only",
        steps=["解析公司和岗位", "生成 LinkedIn people search", "打开候选搜索页", "采样 recruiter / hiring manager 主页"],
        output={
            "linkedin_contact_search": {
                "source": "linkedin",
                "search_terms": search_terms,
                "keywords": keywords,
                "target_url": search_url,
                "expected_event_type": "linkedin_contact_snapshot",
                "command": command,
                "safety": {
                    "read_only": True,
                    "external_side_effect": False,
                    "blocked_actions": ["connect", "message", "apply", "submit"],
                },
            },
            "next_actions": ["等待云端浏览器打开搜索页", "由 collector 采样候选 profile", "生成外联草稿前仍需 JD + 简历 + 用户确认"],
        },
        provider_calls=[
            {
                "provider": "managed_browser",
                "action": "browser.open_linkedin_contact_search",
                "status": "planned" if status == "ready_for_browser_navigation" else "blocked_missing_slots",
                "external_side_effect": False,
                "url": search_url,
                "command": command,
            }
        ] if status == "ready_for_browser_navigation" else [],
        writeback_targets=["task_trace", "collector_health", "memory_items"],
        writeback_plan=[
            {
                "target": "task_trace",
                "operation": "append_browser_navigation_plan",
                "payload": {
                    "source": "linkedin",
                    "target_url": search_url,
                    "expected_event_type": "linkedin_contact_snapshot",
                    "source_event_ids": _as_list(context.get("source_event_ids")),
                },
            }
        ] if status == "ready_for_browser_navigation" else [],
    )


def _effective_resume_for_matching(resume: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    effective = dict(resume or {})
    if not effective and profile:
        effective = dict(profile)
    skills = _ordered_unique([*_as_list(effective.get("skills")), *_as_list(profile.get("skills"))])
    if skills:
        effective["skills"] = skills
    target_roles = _ordered_unique([*_as_list(effective.get("target_roles")), *_as_list(profile.get("target_roles"))])
    if target_roles:
        effective["target_roles"] = target_roles
    target_locations = _ordered_unique([*_as_list(effective.get("target_locations")), *_as_list(profile.get("target_locations"))])
    if target_locations:
        effective["target_locations"] = target_locations
    if not effective.get("resume_id"):
        effective["resume_id"] = resume.get("resume_id") or profile.get("resume_id") or profile.get("career_profile_id")
    return effective


def _score_job_recommendation(job: dict[str, Any], resume: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    actionable_url, url_validation_status = _actionable_job_url(job.get("url"))
    matched, gaps = _match_requirements(job, resume)
    requirements = _job_requirements(job)
    jd_text = str(job.get("jd_text") or "")
    requirement_score = (len(matched) / max(len(requirements), 1)) * 0.60 if requirements else 0.0
    role_score = _recommendation_role_score(job, resume, profile)
    location_score = _recommendation_location_score(job, resume, profile)
    evidence_score = 0.08 if len(jd_text) >= 120 and job.get("title") and job.get("company") and actionable_url else 0.02
    penalty = 0.20 if len(jd_text) < 60 or not job.get("title") or not job.get("company") else 0.0
    score = max(0.0, min(1.0, round(requirement_score + role_score + location_score + evidence_score - penalty, 2)))
    tier = _recommendation_tier(score)
    return {
        **job,
        "raw_url": str(job.get("url") or ""),
        "url": actionable_url,
        "url_validation_status": url_validation_status,
        "fit_score": score,
        "recommendation_tier": tier,
        "matched_requirements": matched,
        "gap_requirements": gaps,
        "recommendation_reasons": matched[:4],
        "summary": _job_summary(job, matched, gaps),
        "why_recommended": _why_recommended(job, matched, score),
        "why_not_top_match": _why_not_top_match(gaps, job),
        "evidence_ids": _ordered_unique([*_as_list(job.get("source_event_ids")), *_evidence_ids({}, resume)]),
        "unsupported_claims": [],
        "actions": _job_recommendation_actions({**job, "url": actionable_url}),
    }


def _recommendation_role_score(job: dict[str, Any], resume: dict[str, Any], profile: dict[str, Any]) -> float:
    title = str(job.get("title") or "").lower()
    role_text = " ".join([*_as_list(resume.get("target_roles")), *_as_list(profile.get("target_roles")), str(resume.get("headline") or "")]).lower()
    title_tokens = {token for token in re.split(r"[^a-zA-Z0-9]+", title) if len(token) > 2}
    role_tokens = {token for token in re.split(r"[^a-zA-Z0-9]+", role_text) if len(token) > 2}
    if title_tokens and role_tokens and title_tokens.intersection(role_tokens):
        return 0.18
    return _role_bonus(job, resume)


def _recommendation_location_score(job: dict[str, Any], resume: dict[str, Any], profile: dict[str, Any]) -> float:
    location = str(job.get("location") or "").lower()
    target_locations = " ".join([*_as_list(resume.get("target_locations")), *_as_list(profile.get("target_locations"))]).lower()
    if not location or not target_locations:
        return 0.04
    if "remote" in location and "remote" in target_locations:
        return 0.08
    for token in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", target_locations):
        if len(token) >= 2 and token in location:
            return 0.08
    return 0.0


def _recommendation_tier(score: float) -> str:
    if score >= 0.75:
        return "strong_fit"
    if score >= 0.65:
        return "good_fit"
    if score >= 0.55:
        return "possible_fit"
    return "low_fit"


def _job_summary(job: dict[str, Any], matched: list[str], gaps: list[str]) -> str:
    title = job.get("title") or "未命名岗位"
    company = job.get("company") or "未知公司"
    location = job.get("location") or "地点未明"
    matched_text = "、".join(matched[:3]) if matched else "暂无明确命中项"
    gap_text = "、".join(gaps[:2]) if gaps else "暂未发现明显缺口"
    return f"{company} 的 {title}，地点 {location}。命中：{matched_text}。缺口：{gap_text}。"


def _why_recommended(job: dict[str, Any], matched: list[str], score: float) -> str:
    if matched:
        return f"匹配度 {score:.2f}，JD 中的 {', '.join(matched[:4])} 与简历/职业画像有证据对应。"
    return f"匹配度 {score:.2f}，但 JD 证据较少，只作为低置信候选。"


def _why_not_top_match(gaps: list[str], job: dict[str, Any]) -> str:
    if gaps:
        return f"简历中暂未明确覆盖：{', '.join(gaps[:3])}。"
    if len(str(job.get("jd_text") or "")) < 120:
        return "JD 文本较短，证据不足。"
    return "主要要求已覆盖。"


def _actionable_job_url(raw_url: Any) -> tuple[str, str]:
    url = str(raw_url or "").strip()
    if not url:
        return "", "missing"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", "invalid_url"
    value = f"{parsed.netloc}{parsed.path}".lower()
    placeholder_terms = (
        "example.com",
        "example.test",
        "exampleai",
        "example-ai",
        "acme",
        "localhost",
        "127.0.0.1",
    )
    if any(term in value for term in placeholder_terms):
        return "", "placeholder_or_test_url"
    return url, "actionable"


def _job_recommendation_actions(job: dict[str, Any]) -> list[dict[str, Any]]:
    job_id = str(job.get("job_id") or "")
    url = str(job.get("url") or "")
    actions = []
    if url:
        actions.append({"id": "open_job_url", "label": "打开岗位链接", "risk": "read_only", "url": url})
    actions.extend([
        {"id": "add_to_career_board", "label": "加入求职看板", "risk": "write", "target_pipeline": "application_tracking_pipeline", "job_id": job_id},
        {"id": "tailor_resume", "label": "改简历", "risk": "draft", "target_pipeline": "resume_tailoring_pipeline", "job_id": job_id},
        {"id": "find_hr", "label": "联系HR", "risk": "draft", "target_pipeline": "linkedin_contact_search_pipeline", "job_id": job_id},
        {"id": "dismiss", "label": "忽略", "risk": "local_only", "job_id": job_id},
    ])
    return actions


def _job_recommendation_summary(recommendations: list[dict[str, Any]]) -> str:
    if not recommendations:
        return "没有达到推荐阈值的岗位。"
    top = recommendations[0]
    return (
        f"发现 {len(recommendations)} 个较匹配岗位，最高匹配 {top.get('fit_score', 0):.2f}："
        f"{top.get('company')} - {top.get('title')}。"
    )


def _job_recommendation_suggestion_payload(recommendations: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    top = recommendations[0]
    lines = [
        _job_recommendation_summary(recommendations),
        "",
        f"推荐岗位：{top.get('title')} @ {top.get('company')}",
        f"地点：{top.get('location') or '未明确'}",
        f"匹配度：{top.get('fit_score', 0):.2f}（{top.get('recommendation_tier')}）",
        f"岗位总结：{top.get('summary')}",
        f"推荐理由：{'、'.join(top.get('recommendation_reasons') or []) or top.get('why_recommended')}",
        f"主要缺口：{'、'.join(top.get('gap_requirements') or []) or '暂未发现明显缺口'}",
    ]
    if top.get("url"):
        lines.append(f"链接：{top.get('url')}")
    else:
        lines.append("链接：链接待验证，暂不提供打开按钮。")
    return {
        "title": "发现高匹配岗位",
        "body": "\n".join(lines),
        "priority": min(1.0, max(0.0, float(top.get("fit_score") or 0))),
        "status": "open",
        "source_event_id": (_as_list(context.get("source_event_ids")) or [""])[0],
        "metadata": {
            "suggestion_type": "career_job_recommendation",
            "source": "career_job_recommendation_pipeline",
            "dedupe_key": f"career_job_recommendation:{top.get('job_id') or top.get('url')}",
            "recommended_jobs": [
                {
                    "job_id": item.get("job_id"),
                    "title": item.get("title"),
                    "company": item.get("company"),
                    "location": item.get("location"),
                    "url": item.get("url"),
                    "url_validation_status": item.get("url_validation_status"),
                    "fit_score": item.get("fit_score"),
                    "recommendation_tier": item.get("recommendation_tier"),
                    "summary": item.get("summary"),
                    "recommendation_reasons": item.get("recommendation_reasons"),
                    "gap_requirements": item.get("gap_requirements"),
                }
                for item in recommendations
            ],
            "actions": top.get("actions") or _job_recommendation_actions(top),
        },
    }


def _job_writeback_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": item.get("job_id"),
        "source": item.get("source"),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "url": item.get("url"),
        "status": "recommended" if item.get("recommendation_tier") in {"strong_fit", "good_fit"} else "screened_out",
        "fit_score": item.get("fit_score"),
        "requirements": item.get("requirements") or [],
        "source_event_ids": item.get("source_event_ids") or [],
        "matched_requirements": item.get("matched_requirements") or [],
        "gap_requirements": item.get("gap_requirements") or [],
        "recommendation_tier": item.get("recommendation_tier"),
        "summary": item.get("summary"),
        "url_openable": bool(item.get("url")),
    }


def _normalize_job(job: dict[str, Any] | None, *, index: int = 0) -> dict[str, Any]:
    job = dict(job or {})
    title = str(job.get("title") or job.get("role") or "").strip()
    company = str(job.get("company") or "").strip()
    job_id = str(job.get("job_id") or job.get("id") or "").strip()
    if not job_id and (title or company):
        job_id = f"job_{_slug(title or 'role')}_{_slug(company or str(index))}"
    jd_text = str(job.get("jd_text") or job.get("description") or job.get("content") or job.get("text") or "").strip()
    return {
        "job_id": job_id,
        "source": str(job.get("source") or "manual"),
        "title": title,
        "company": company,
        "location": str(job.get("location") or ""),
        "url": str(job.get("url") or job.get("profile_url") or ""),
        "jd_text": jd_text,
        "requirements": _ordered_unique([*_as_list(job.get("requirements")), *_extract_requirements(jd_text)]),
        "source_event_ids": _as_list(job.get("source_event_ids")),
    }


def _resume(context: dict[str, Any]) -> dict[str, Any]:
    resume = context.get("resume") if isinstance(context.get("resume"), dict) else {}
    if not resume and isinstance(context.get("career_profile"), dict):
        resume = context["career_profile"]
    return dict(resume or {})


def _career_profile(context: dict[str, Any]) -> dict[str, Any]:
    return dict(context.get("career_profile") or {}) if isinstance(context.get("career_profile"), dict) else {}


def _job(context: dict[str, Any]) -> dict[str, Any]:
    if isinstance(context.get("job"), dict):
        return dict(context["job"])
    if isinstance(context.get("job_opportunity"), dict):
        return dict(context["job_opportunity"])
    jobs = _jobs(context)
    return jobs[0] if jobs else {}


def _jobs(context: dict[str, Any]) -> list[dict[str, Any]]:
    raw = context.get("jobs") or context.get("job_opportunities") or []
    if isinstance(raw, dict):
        raw = [raw]
    return [dict(item) for item in raw if isinstance(item, dict)]


def _jobs_from_pages(context: dict[str, Any]) -> list[dict[str, Any]]:
    raw = context.get("job_pages") or context.get("ats_pages") or []
    if isinstance(raw, dict):
        raw = [raw]
    jobs: list[dict[str, Any]] = []
    context_source_event_ids = _as_list(context.get("source_event_ids"))
    for index, page in enumerate(raw):
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or "")
        text = str(page.get("text") or page.get("content") or page.get("html_text") or "")
        title_from_page = str(page.get("title") or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        source = str(page.get("source") or "").strip() or _ats_source(url)
        if source == "linkedin_browser_observation":
            title = title_from_page or _page_title(title_from_page, lines)
        else:
            title = _page_title(title_from_page, lines)
        company = str(page.get("company") or "").strip() or _page_company(title_from_page, title, lines, url)
        location = str(page.get("location") or "").strip() or _page_location(lines)
        source_event_ids = [str(page.get("source_event_id"))] if page.get("source_event_id") else _as_list(page.get("source_event_ids"))
        if not source_event_ids:
            source_event_ids = context_source_event_ids
        jobs.append(
            {
                "job_id": str(page.get("job_id") or page.get("id") or f"job_{_slug(title or 'role')}_{_slug(company or str(index))}"),
                "source": source,
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "jd_text": text,
                "requirements": _extract_requirements(text),
                "source_event_ids": source_event_ids,
            }
        )
    return jobs


def _jobs_from_web_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    raw = context.get("web_context") or []
    if isinstance(raw, dict):
        raw = [raw]
    pages = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("layer") or "") != "web_evidence":
            continue
        url = str(item.get("url") or "").strip()
        if not url or _ats_source(url) == "public_ats":
            continue
        pages.append(
            {
                "url": url,
                "title": item.get("title"),
                "text": item.get("content") or item.get("snippet") or "",
                "source_event_id": item.get("source_id"),
            }
        )
    return _jobs_from_pages({"job_pages": pages})


def _contact(context: dict[str, Any]) -> dict[str, Any]:
    return dict(context.get("contact") or {}) if isinstance(context.get("contact"), dict) else {}


def _resume_skills(resume: dict[str, Any]) -> list[str]:
    skills = _as_list(resume.get("skills"))
    text = " ".join([str(resume.get("headline") or ""), str(resume.get("summary") or "")])
    for requirement in [
        "Java",
        "Go",
        "JVM tuning",
        "high concurrency",
        "high availability",
        "distributed systems",
        "microservices",
        "Kafka",
        "RocketMQ",
        "Redis",
        "Elasticsearch",
        "MySQL",
        "sharding",
        "DDD",
        "SQL optimization",
        "Spark",
        "Hive",
        "observability",
        "team leadership",
        "AI Agent",
        "LLM product",
        "workflow automation",
        "data analysis",
        "B2B SaaS",
        "cross-functional collaboration",
    ]:
        if requirement.lower() in text.lower():
            skills.append(requirement)
    return _ordered_unique(skills)


def _job_requirements(job: dict[str, Any]) -> list[str]:
    return _ordered_unique(_as_list(job.get("requirements")) or _extract_requirements(str(job.get("jd_text") or "")))


def _match_requirements(job: dict[str, Any], resume: dict[str, Any]) -> tuple[list[str], list[str]]:
    requirements = _job_requirements(job)
    resume_text = _flatten_text(resume)
    matched: list[str] = []
    gaps: list[str] = []
    for requirement in requirements:
        if _requirement_matches(requirement, resume_text):
            matched.append(requirement)
        else:
            gaps.append(requirement)
    return _ordered_unique(matched), _ordered_unique(gaps)


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-()]{6,}\d)(?!\d)")


def _sanitize_external_resume_text(text: Any) -> str:
    value = str(text or "")
    value = EMAIL_RE.sub("[email redacted]", value)
    value = PHONE_RE.sub("[phone redacted]", value)
    value = re.sub(r"基本信息[:：].*?(?=(技术能力|工作经历|项目经历|$))", "", value, flags=re.S)
    value = re.sub(r"(联系方式|电话|手机|邮箱|邮件)[:：]?\s*\S+", "", value)
    value = re.sub(r"\s+", " ", value).strip(" ，,。.;；")
    return value


def _cover_letter_display_skills(job: dict[str, Any], resume: dict[str, Any], matched_requirements: list[str]) -> list[str]:
    skills = _ordered_unique([*matched_requirements, *_resume_skills(resume), *_as_list(resume.get("skills"))])
    text = _flatten_text({"job": job, "resume": resume}).lower()
    promoted: list[str] = []
    if "ai agent" in text or " agent" in text or "智能体" in text:
        promoted.append("AI Agent")
    if "llm" in text or "大模型" in text:
        promoted.append("LLM product")
    if "workflow" in text or "automation" in text or "自动化" in text:
        promoted.append("workflow automation")
    return _ordered_unique([*promoted, *skills])


def _cover_letter_resume_highlights(resume: dict[str, Any], matched_requirements: list[str]) -> str:
    skills = _ordered_unique([*matched_requirements, *_resume_skills(resume), *_as_list(resume.get("skills"))])
    candidate_sentences: list[str] = []
    for item in resume.get("experience") or []:
        if isinstance(item, dict):
            summary = _sanitize_external_resume_text(item.get("summary") or item.get("description") or "")
            role = _sanitize_external_resume_text(item.get("role") or "")
            company = _sanitize_external_resume_text(item.get("company") or "")
            if summary:
                prefix = " / ".join(part for part in [company, role] if part)
                candidate_sentences.append(f"{prefix}: {summary}" if prefix else summary)
    summary = _sanitize_external_resume_text(resume.get("summary") or "")
    for part in re.split(r"(?<=[。.!！？?])\s*|[；;]\s*", summary):
        part = part.strip()
        if part:
            candidate_sentences.append(part)

    keyword_text = " ".join(skills).lower()
    preferred: list[str] = []
    for sentence in candidate_sentences:
        lowered = sentence.lower()
        if any(keyword.lower() in lowered for keyword in skills if keyword) or any(
            marker in lowered for marker in ["ai agent", "llm", "java", "go", "高并发", "架构", "leader", "automation", "workflow"]
        ):
            preferred.append(sentence)
    if not preferred:
        preferred = candidate_sentences

    highlights = " ".join(preferred[:2]).strip()
    if not highlights:
        highlights = str(resume.get("headline") or "relevant engineering and AI product work")
    highlights = _sanitize_external_resume_text(highlights)
    if len(highlights) > 260:
        highlights = highlights[:257].rstrip(" ，,。.;；") + "..."
    if skills and not any(skill.lower() in highlights.lower() for skill in skills if skill):
        highlights = f"{highlights}; key skills: {', '.join(skills[:3])}"
    return highlights


def _extract_requirements(text: str) -> list[str]:
    aliases = _requirement_aliases()
    lowered = f" {str(text or '').lower()} "
    matched: list[str] = []
    for requirement, terms in aliases.items():
        if any(term.lower() in lowered for term in terms):
            matched.append(requirement)
    return _ordered_unique(matched)


def _requirement_matches(requirement: str, resume_text: str) -> bool:
    lowered = resume_text.lower()
    if requirement.lower() in lowered:
        return True
    aliases = _requirement_aliases()
    return any(alias.lower() in lowered for alias in aliases.get(requirement, []))


def _requirement_aliases() -> dict[str, list[str]]:
    return {
        "Java": ["java"],
        "Go": [" go ", "golang", "熟悉 go", "go、", "go。"],
        "JVM tuning": ["jvm", "gc", "fullgc", "垃圾回收", "调优"],
        "high concurrency": ["high concurrency", "高并发", "tps", "concurrency"],
        "high availability": ["high availability", "高可用", "availability"],
        "distributed systems": ["distributed systems", "分布式"],
        "microservices": ["microservices", "microservice", "微服务"],
        "Kafka": ["kafka"],
        "RocketMQ": ["rocketmq", "rocket mq"],
        "Redis": ["redis"],
        "Elasticsearch": ["elasticsearch", "elastic search", " es "],
        "MySQL": ["mysql"],
        "sharding": ["sharding", "分库分表"],
        "DDD": ["ddd", "领域驱动"],
        "SQL optimization": ["sql optimization", "sql tuning", "sql 调优", "sql优化"],
        "Spark": ["spark"],
        "Hive": ["hive"],
        "observability": ["observability", "otel", "prometheus", "grafana", "可观测"],
        "team leadership": ["team leadership", "leader", "technical owner", "技术 owner", "技术owner", "管理"],
        "AI Agent": ["ai agent", "智能体", "harness"],
        "cross-functional collaboration": ["cross functional", "cross-functional", "collaboration", "跨职能", "协作"],
        "LLM product": ["llm", "large language model", "大模型"],
        "workflow automation": ["automation", "workflow", "自动化"],
        "data analysis": ["analytics", "analysis", "数据"],
        "B2B SaaS": ["b2b", "saas", "tob"],
        "ATS": ["ats"],
        "LinkedIn outreach": ["linkedin outreach", "linkedin 外联"],
        "resume writing": ["resume writing", "简历"],
    }


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join([_flatten_text(item) for item in value.values()])
    if isinstance(value, list):
        return " ".join([_flatten_text(item) for item in value])
    return str(value or "")


def _evidence_ids(context: dict[str, Any], resume: dict[str, Any] | None = None, *, extra: list[str] | None = None) -> list[str]:
    ids = [str(item) for item in context.get("source_event_ids") or []]
    resume = resume or {}
    for item in resume.get("experience") or []:
        if isinstance(item, dict) and item.get("evidence_id"):
            ids.append(str(item["evidence_id"]))
    ids.extend(str(item) for item in extra or [])
    return _ordered_unique([item for item in ids if item])


def _role_bonus(job: dict[str, Any], resume: dict[str, Any]) -> float:
    title = str(job.get("title") or "").lower()
    headline = str(resume.get("headline") or "").lower()
    resume_text = _flatten_text(resume).lower()
    if title and any(part for part in re.split(r"[^a-zA-Z0-9]+", title) if len(part) > 2 and part in headline):
        return 0.18
    if ("backend" in title or "architect" in title) and any(marker in resume_text for marker in ["后端", "架构", "java"]):
        return 0.18
    return 0.08


def _extract_job_query(request: str) -> str:
    cleaned = re.sub(r"^(帮我|请|给我|寻找|找)", "", request).strip(" ：:，,。.!！?？")
    return cleaned or request


def _extract_role(request: str) -> str:
    match = re.search(r"([A-Za-z0-9\u4e00-\u9fff ]{2,40}(?:经理|PM|工程师|产品|运营|设计|sales|manager))", request, flags=re.I)
    return match.group(1).strip() if match else ""


def _normalize_role_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "ai product manager" in lowered or "ai pm" in lowered or "ai 产品经理" in text:
        return "AI Product Manager"
    if "product manager" in lowered or "product lead" in lowered or "产品经理" in text or re.search(r"\bpm\b", lowered):
        return "Product Manager"
    if "sales manager" in lowered or "销售经理" in text:
        return "Sales Manager"
    if "designer" in lowered or "设计师" in text:
        return "Designer"
    english_engineer = re.search(
        r"\b((?:senior|staff|lead|principal)?\s*(?:backend|front[- ]?end|full[- ]?stack|software|data|ai|ml|machine learning|platform|infra|infrastructure)?\s*engineer)\b",
        text,
        flags=re.I,
    )
    if english_engineer:
        return re.sub(r"\s+", " ", english_engineer.group(1)).strip().title().replace("Ai ", "AI ").replace("Ml ", "ML ")
    if "engineer" in lowered or "工程师" in text:
        extracted = _extract_role(text)
        return extracted or "Engineer"
    extracted = _extract_role(text)
    return extracted or text


def _target_roles(request: str, context: dict[str, Any], resume: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    explicit_roles = _as_list(profile.get("target_roles")) or _as_list(context.get("target_roles"))
    candidates = [
        *explicit_roles,
        _extract_role(request),
        _job(context).get("title", ""),
        resume.get("target_role", ""),
        resume.get("headline", ""),
    ]
    return _ordered_unique([_normalize_role_text(candidate) for candidate in candidates])


def _application_action(request: str) -> str:
    lowered = request.lower()
    if any(term in lowered for term in ["submit", "提交"]):
        return "submit_application"
    if any(term in lowered for term in ["apply", "投递", "申请"]):
        return "click_apply"
    return "prepare_application"


def _platform_for_job(job: dict[str, Any]) -> str:
    source = str(job.get("source") or "").lower()
    url = str(job.get("url") or "").lower()
    if "linkedin" in source or "linkedin" in url:
        return "linkedin"
    if "greenhouse" in source or "greenhouse" in url:
        return "greenhouse"
    if "lever" in source or "lever" in url:
        return "lever"
    if "ashby" in source or "ashby" in url:
        return "ashby"
    return source or "job_board"


def _ats_source(url: str) -> str:
    lowered = str(url or "").lower()
    if "greenhouse.io" in lowered:
        return "greenhouse_public"
    if "jobs.lever.co" in lowered or "lever.co" in lowered:
        return "lever_public"
    if "ashbyhq.com" in lowered:
        return "ashby_public"
    if "workable.com" in lowered:
        return "workable_public"
    if "smartrecruiters.com" in lowered:
        return "smartrecruiters_public"
    if "linkedin.com" in lowered:
        return "linkedin_browser_observation"
    return "job_page_observation"


def _page_title(page_title: str, lines: list[str]) -> str:
    if page_title:
        cleaned = re.split(r"\s[-|]\s", page_title, maxsplit=1)[0].strip()
        if cleaned:
            return cleaned
    return lines[0] if lines else ""


def _page_company(page_title: str, title: str, lines: list[str], url: str) -> str:
    if " - " in page_title:
        tail = page_title.split(" - ", 1)[1].strip()
        if tail:
            return tail
    if len(lines) > 1 and lines[1].lower() not in {"remote", "hybrid", "onsite"} and not lines[1].lower().startswith("location:"):
        return lines[1]
    match = re.search(r"/(?:boards\.greenhouse\.io|jobs\.lever\.co)/([^/]+)/", url)
    if match:
        return match.group(1).replace("-", " ").replace("_", " ").title()
    return ""


def _page_location(lines: list[str]) -> str:
    for line in lines:
        if line.lower().startswith("location:"):
            return line.split(":", 1)[1].strip()
        if line.lower() in {"remote", "hybrid", "onsite"}:
            return line
        if any(marker in line.lower() for marker in ["remote", "hybrid", "on-site", "onsite", "china", "beijing", "shanghai", "shenzhen"]):
            return line.split("·", 1)[0].strip()
    return ""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None and value != "" and value != []}


def _missing(values: dict[str, Any], required: list[str]) -> list[str]:
    return [key for key in required if values.get(key) is None or values.get(key) == "" or values.get(key) == []]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")[:40] or "unknown"

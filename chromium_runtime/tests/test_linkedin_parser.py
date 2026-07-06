import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_parse_linkedin_feed_snapshot_extracts_visible_profile_and_job_prompt():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "Home",
        "My Network",
        "Jobs",
        "Messaging",
        "张子长",
        "Program Manager at Beijing Sankuai Technology Ltd.",
        "Beijing",
        "Beijing Sankuai Technology Ltd.",
        "Connections",
        "Grow your network",
        "Hi 张子长, are you looking for a job right now?",
        "Your response is only visible to you",
        "Yes",
        "No",
        "Feed post",
        "Suggested",
        "Alex R.",
        "Robotics and AI Systems Architect",
        "Follow",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/feed/",
        title="Feed | LinkedIn",
        lines=lines,
    )

    event_types = [item["event_type"] for item in snapshots]
    assert "linkedin_visible_snapshot" in event_types
    assert "linkedin_profile_snapshot" in event_types
    assert "linkedin_career_prompt" in event_types

    profile = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_profile_snapshot")
    assert profile["profile_name"] == "张子长"
    assert profile["headline"] == "Program Manager at Beijing Sankuai Technology Ltd."
    assert profile["location"] == "Beijing"
    assert profile["company"] == "Beijing Sankuai Technology Ltd."
    assert profile["capture_scope"] == "visible_profile_snapshot"

    prompt = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_career_prompt")
    assert prompt["prompt"] == "Hi 张子长, are you looking for a job right now?"
    assert prompt["available_answers"] == ["Yes", "No"]


def test_parse_linkedin_job_detail_snapshot_outputs_job_page_for_career_pipeline():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "AI Product Manager",
        "Example AI",
        "Shanghai, China · Reposted 2 days ago",
        "Full-time",
        "About the job",
        "We need an AI Product Manager with LLM product experience, workflow automation, and data analysis.",
        "Responsibilities",
        "Drive cross-functional collaboration and ship B2B SaaS workflows.",
        "Apply",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/jobs/view/123456789/",
        title="AI Product Manager - Example AI | LinkedIn",
        lines=lines,
    )

    job = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_description_snapshot")
    assert job["job_pages"][0]["title"] == "AI Product Manager"
    assert job["job_pages"][0]["company"] == "Example AI"
    assert job["job_pages"][0]["location"] == "Shanghai, China"
    assert "LLM product experience" in job["job_pages"][0]["text"]
    assert job["capture_scope"] == "opened_job_description"


def test_parse_linkedin_job_detail_ignores_navigation_notification_noise():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "0 notifications",
        "2",
        "China",
        "Home",
        "Jobs",
        "Messaging",
        "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
        "A1",
        "China · Reposted 1 month ago · Over 100 applicants",
        "Promoted by hirer",
        "Remote",
        "Full-time",
        "Easy Apply",
        "About the job",
        "Build AI Agent backend systems with workflow orchestration and reliable APIs.",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/jobs/view/4378789245/",
        title="LinkedIn",
        lines=lines,
    )

    job = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_description_snapshot")
    assert job["job_pages"][0]["title"] == "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems"
    assert job["job_pages"][0]["company"] == "A1"
    assert job["job_pages"][0]["location"] == "China"
    assert "0 notifications" not in job["job_pages"][0]["title"]


def test_parse_linkedin_real_job_detail_prefers_title_company_over_response_noise():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "0 notifications",
        "Skip to footer",
        "2",
        "14",
        "BJAK",
        "Backend Engineer, AI (Agent Systems)",
        "Beijing, Beijing, China · 3 months ago · 37 people clicked apply",
        "Responses managed off LinkedIn",
        "Remote",
        "Full-time",
        "Apply",
        "Save",
        "Use AI to assess how you fit",
        "Unable to load your job match data",
        "About the job",
        "Company",
        "A1 is building a proactive AI smart assistant for everyday users.",
        "Role",
        "As a Backend Engineer, AI, you own the inference and orchestration layer.",
        "Ideal Experiences",
        "Experience running high-throughput, low-latency services.",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/jobs/view/4388714215/",
        title="Backend Engineer, AI (Agent Systems) | BJAK | LinkedIn",
        lines=lines,
    )

    job = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_description_snapshot")
    page = job["job_pages"][0]
    assert page["title"] == "Backend Engineer, AI (Agent Systems)"
    assert page["company"] == "BJAK"
    assert page["location"] == "Beijing, Beijing, China"
    assert page["company"] != "Responses managed off LinkedIn"
    assert "Responses managed off LinkedIn 的 Backend" not in page["text"]


def test_parse_linkedin_real_job_search_sample_keeps_only_reasonable_job_cards():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "Jobs search",
        "Jobs",
        "Past 24 hours",
        "Remote",
        "Try AI job search",
        "AI Product Manager in China",
        "3 results",
        "Set alert",
        "Set job alert for AI Product Manager in China",
        "Jump to active job details",
        "Jump to active search result",
        "交易产品经理（跟单交易 & 量化策略）",
        "Confidential",
        "Shenzhen, Guangdong, China (Remote)",
        "Viewed",
        "Promoted",
        "Easy Apply",
        "交易产品经理（跟单交易 & 量化策略）",
        "Confidential",
        "Shanghai, China (Remote)",
        "Promoted",
        "Easy Apply",
        "Product Designer / Venture Product Builder (Work From Home)",
        "Persona",
        "APAC (Remote)",
        "5 hours ago",
        "Within the past 24 hours",
        "Are these results helpful?",
        "Expand your search",
        "Senior Customer Program Manager – Server and Networking Products",
        "NVIDIA",
        "Beijing, Beijing, China (On-site)",
        "Program Manager II, Product Program Management",
        "Amazon",
        "Beijing, Beijing, China (On-site)",
        "AIGC内容安全产品经理-CapCut",
        "ByteDance",
        "Beijing, Beijing, China (On-site)",
        "Confidential",
        "Share",
        "Show more options",
        "交易产品经理（跟单交易 & 量化策略）",
        "Shenzhen, Guangdong, China · 21 hours ago · 1 applicant",
        "Remote",
        "Full-time",
        "Save 交易产品经理（跟单交易 & 量化策略） at Confidential",
        "About the job",
        "关于公司",
        "我们是全球最早也是最成熟的数字资产平台之一，服务于全球数千万用户。",
        "你会负责",
        "推动经典机器人策略优化、AI 策略探索、策略表现与归因展示等功能落地",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/jobs/search/?keywords=AI%20Product%20Manager",
        title="(2) AI Product Manager Jobs | LinkedIn",
        lines=lines,
    )

    search = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_search_results")
    titles = [job["title"] for job in search["job_results"]]
    assert titles == [
        "交易产品经理（跟单交易 & 量化策略）",
        "Product Designer / Venture Product Builder (Work From Home)",
        "Senior Customer Program Manager – Server and Networking Products",
        "Program Manager II, Product Program Management",
        "AIGC内容安全产品经理-CapCut",
    ]
    assert search["job_results"][0]["company"] == "Confidential"
    assert search["job_results"][0]["location"] == "Shenzhen, Guangdong, China (Remote)"
    assert all("Set job alert" not in title for title in titles)
    assert all(not title.startswith("Save ") for title in titles)

    detail = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_description_snapshot")
    active_job = detail["job_pages"][0]
    assert active_job["title"] == "交易产品经理（跟单交易 & 量化策略）"
    assert active_job["company"] == "Confidential"
    assert active_job["location"] == "Shenzhen, Guangdong, China"
    assert "AI 策略探索" in active_job["text"]


def test_parse_linkedin_job_search_results_uses_job_specific_links_from_dom_hints():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "Jobs search",
        "Jump to active search result",
        "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
        "A1",
        "China (Remote)",
        "Viewed",
        "Easy Apply",
        "Backend Development Engineer (C++)",
        "Bybit",
        "China (Remote)",
        "Actively reviewing applicants",
        "Be an early applicant",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/jobs/search/?currentJobId=4428708717&keywords=Backend%20Engineer%20AI%20Agent",
        title="(16) Backend Engineer AI Agent Jobs | LinkedIn",
        lines=lines,
        job_link_hints=[
            {
                "title": "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems",
                "company": "A1",
                "href": "https://www.linkedin.com/jobs/view/4428708717/?trackingId=abc",
                "text": "后端开发工程师（AI Agent系统） | Backend Engineer, AI Systems\nA1\nChina (Remote)",
            },
            {
                "title": "Backend Development Engineer (C++)",
                "company": "Bybit",
                "href": "https://www.linkedin.com/jobs/search/?currentJobId=4378789245&keywords=Backend%20Engineer",
                "text": "Backend Development Engineer (C++)\nBybit\nChina (Remote)",
            },
        ],
    )

    search = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_job_search_results")
    assert search["job_results"][0]["url"] == "https://www.linkedin.com/jobs/view/4428708717/"
    assert search["job_results"][1]["url"] == "https://www.linkedin.com/jobs/view/4378789245/"


def test_parse_linkedin_recruiter_profile_outputs_contact_snapshot_for_outreach():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "Home",
        "My Network",
        "Jobs",
        "Messaging",
        "Jane Chen",
        "Senior Technical Recruiter at Example AI",
        "Singapore",
        "Example AI",
        "500+ connections",
        "Message",
        "Connect",
        "More",
        "About",
        "I recruit backend engineers and distributed systems architects across APAC.",
        "Experience",
        "Senior Technical Recruiter",
        "Example AI",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/in/jane-chen-recruiter/",
        title="Jane Chen | LinkedIn",
        lines=lines,
    )

    contact = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_contact_snapshot")
    assert contact["contact_id"].startswith("linkedin_contact_")
    assert contact["name"] == "Jane Chen"
    assert contact["headline"] == "Senior Technical Recruiter at Example AI"
    assert contact["company"] == "Example AI"
    assert contact["location"] == "Singapore"
    assert contact["contact_kind"] == "recruiter"
    assert contact["channel"] == "linkedin"
    assert contact["profile_url"] == "https://www.linkedin.com/in/jane-chen-recruiter/"
    assert contact["available_actions"] == ["draft_message", "request_connection"]
    assert "backend engineers" in contact["text"]


def test_extract_linkedin_recruiter_profile_links_prefers_hiring_team_people():
    from app.runtime import extract_linkedin_recruiter_profile_links

    links = extract_linkedin_recruiter_profile_links(
        [
            {
                "href": "https://www.linkedin.com/in/backend-engineer/",
                "text": "Backend Engineer at Example AI",
                "aria_label": "View profile",
            },
            {
                "href": "https://www.linkedin.com/in/jane-chen-recruiter/?miniProfileUrn=abc",
                "text": "Jane Chen Senior Technical Recruiter at Example AI Message",
                "aria_label": "View Jane Chen profile",
            },
            {
                "href": "https://www.linkedin.com/jobs/view/123",
                "text": "Apply",
                "aria_label": "Apply",
            },
        ]
    )

    assert links == ["https://www.linkedin.com/in/jane-chen-recruiter/"]


def test_people_search_page_auto_opens_recruiter_profile(monkeypatch):
    from app import runtime

    opened = []
    health = []

    async def fake_report_health(client, collector, status, details):
        health.append((collector, status, details))

    class OpenedPage:
        async def goto(self, url, wait_until, timeout):
            opened.append((url, wait_until, timeout))

    class Context:
        async def new_page(self):
            return OpenedPage()

    class Page:
        url = (
            "https://www.linkedin.com/search/results/people/"
            "?keywords=Example%20AI%20Backend%20Engineer%20recruiter"
        )
        context = Context()

        async def title(self):
            return "Example AI Backend Engineer recruiter | LinkedIn"

        async def evaluate(self, script):
            return [
                {
                    "href": "https://www.linkedin.com/in/plain-engineer/",
                    "text": "Backend Engineer at Example AI",
                    "aria_label": "View profile",
                },
                {
                    "href": "https://www.linkedin.com/in/jane-chen-recruiter/?miniProfileUrn=abc",
                    "text": "Jane Chen Senior Technical Recruiter at Example AI Singapore",
                    "aria_label": "View Jane Chen profile",
                },
            ]

    runtime.LINKEDIN_AUTO_OPENED_PROFILES.clear()
    monkeypatch.setattr(runtime, "report_health", fake_report_health)

    asyncio.run(runtime.auto_open_linkedin_recruiter_profile_if_needed(object(), Page(), []))

    assert opened == [("https://www.linkedin.com/in/jane-chen-recruiter/", "domcontentloaded", 30000)]
    assert health[-1][0] == "linkedin"
    assert health[-1][1] == "healthy"
    assert health[-1][2]["auto_opened_profile_url"] == "https://www.linkedin.com/in/jane-chen-recruiter/"
    assert health[-1][2]["expected_event_type"] == "linkedin_contact_snapshot"
    assert health[-1][2]["source_page_kind"] == "people_search"


def test_parse_linkedin_people_search_results_preserves_anonymous_recruiter_candidates():
    from app.runtime import parse_linkedin_visible_page

    lines = [
        "People",
        "1st",
        "2nd",
        "3rd+",
        "Locations",
        "Current companies",
        "All filters",
        "LinkedIn Member",
        "Talent | Building OpenAI in APAC",
        "Singapore",
        "Current: Member of Recruiting Staff at OpenAI",
        "LinkedIn Member",
        "Talent Acquisition Manager | Certified Human Resources Professional®",
        "Jakarta Metropolitan Area",
        "Current: Talent Acquisition Manager at Packet Systems Indonesia",
        "Are these results helpful?",
    ]

    snapshots = parse_linkedin_visible_page(
        url="https://www.linkedin.com/search/results/people/?keywords=OpenAI%20Recruiter",
        title="Search | LinkedIn",
        lines=lines,
    )

    search = next(item["raw_data"] for item in snapshots if item["event_type"] == "linkedin_contact_search_results")
    assert search["capture_scope"] == "visible_people_search_results"
    assert search["profile_link_status"] == "links_unavailable_until_profile_href_visible"
    assert len(search["contacts"]) == 2
    assert search["contacts"][0]["name"] == "LinkedIn Member"
    assert search["contacts"][0]["is_anonymized"] is True
    assert search["contacts"][0]["headline"] == "Talent | Building OpenAI in APAC"
    assert search["contacts"][0]["company_hint"] == "Current: Member of Recruiting Staff at OpenAI"
    assert search["contacts"][0]["contact_kind"] == "recruiter"
    assert search["contacts"][0]["can_open_profile"] is False


def test_people_search_without_profile_links_reports_blocked_reason(monkeypatch):
    from app import runtime

    health = []

    async def fake_report_health(client, collector, status, details):
        health.append((collector, status, details))

    class Page:
        url = "https://www.linkedin.com/search/results/people/?keywords=OpenAI%20Recruiter"

        async def title(self):
            return "Search | LinkedIn"

        async def evaluate(self, script):
            return []

    snapshots = [
        {
            "event_type": "linkedin_contact_search_results",
            "raw_data": {
                "contacts": [{"headline": "Talent | Building OpenAI in APAC"}],
                "profile_link_status": "links_unavailable_until_profile_href_visible",
            },
        }
    ]

    monkeypatch.setattr(runtime, "report_health", fake_report_health)

    result = asyncio.run(runtime.auto_open_linkedin_recruiter_profile_if_needed(object(), Page(), snapshots))

    assert result["status"] == "blocked_no_profile_links"
    assert result["candidate_count"] == 1
    assert health[-1][0] == "linkedin"
    assert health[-1][1] == "degraded"
    assert health[-1][2]["message"].startswith("LinkedIn people search returned recruiter candidates")


def test_collect_linkedin_emits_structured_events_and_healthy_status(monkeypatch):
    from app import runtime

    emitted = []
    health = []

    async def fake_emit_event(client, source, event_type, raw_data):
        emitted.append((source, event_type, raw_data))

    async def fake_report_health(client, collector, status, details):
        health.append((collector, status, details))

    class Locator:
        async def inner_text(self, timeout):
            return "\n".join(
                [
                    "Home",
                    "Jobs",
                    "张子长",
                    "Program Manager at Beijing Sankuai Technology Ltd.",
                    "Beijing",
                    "Beijing Sankuai Technology Ltd.",
                    "Hi 张子长, are you looking for a job right now?",
                    "Your response is only visible to you",
                    "Yes",
                    "No",
                ]
            )

    class Page:
        url = "https://www.linkedin.com/feed/"

        async def title(self):
            return "Feed | LinkedIn"

        def locator(self, selector):
            assert selector == "body"
            return Locator()

    monkeypatch.setattr(runtime, "emit_event", fake_emit_event)
    monkeypatch.setattr(runtime, "report_health", fake_report_health)

    asyncio.run(runtime.collect_linkedin(object(), Page()))

    assert ("linkedin", "linkedin_profile_snapshot") in [(source, event_type) for source, event_type, _ in emitted]
    assert ("linkedin", "linkedin_career_prompt") in [(source, event_type) for source, event_type, _ in emitted]
    assert health[-1][0] == "linkedin"
    assert health[-1][1] == "healthy"
    assert health[-1][2]["snapshot_count"] >= 3

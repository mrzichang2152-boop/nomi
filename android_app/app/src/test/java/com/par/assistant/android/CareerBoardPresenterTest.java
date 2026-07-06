package com.par.assistant.android;

import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

public final class CareerBoardPresenterTest {
    @Test
    public void rendersOpportunityResumeAndBlockedApplicationForCareerBoard() {
        CareerBoardResult board = new CareerBoardResult(
                List.of(
                        new CareerProfile(
                                "career_profile_default",
                                "AI workflow product manager",
                                List.of("AI Product Manager"),
                                List.of("Shanghai"),
                                List.of("LLM product", "workflow automation")
                        )
                ),
                List.of(
                        new JobOpportunity(
                                "job_pm_ai_1",
                                "linkedin_browser",
                                "AI Product Manager",
                                "Example AI",
                                "Shanghai",
                                "https://www.linkedin.com/jobs/view/job_pm_ai_1",
                                "tracked",
                                0.82,
                                List.of("LLM product", "workflow automation")
                        )
                ),
                List.of(
                        new ResumeVersion(
                                "resume_version_resume_base_1_job_pm_ai_1",
                                "resume_base_1",
                                "job_pm_ai_1",
                                "draft"
                        )
                ),
                List.of(
                        new JobApplicationState(
                                "application_job_pm_ai_1_submit_application",
                                "job_pm_ai_1",
                                "blocked_until_delegated_grant",
                                "apply_submit_blocked",
                                "request_delegated_grant_and_target_manifest",
                                "submit_application",
                                "linkedin"
                        )
                )
        );

        List<String> cards = CareerBoardPresenter.cards(board);
        String joined = String.join("\n---\n", cards);

        assertTrue(joined.contains("职业画像"));
        assertTrue(joined.contains("AI workflow product manager"));
        assertTrue(joined.contains("AI Product Manager · Example AI"));
        assertTrue(joined.contains("匹配 82% · tracked"));
        assertTrue(joined.contains("简历草案：draft"));
        assertTrue(joined.contains("申请状态：等待授权"));
        assertTrue(joined.contains("下一步：request_delegated_grant_and_target_manifest"));

        List<CareerBoardAction> actions = CareerBoardPresenter.actions(board);
        assertTrue(actions.get(0).label.equals("标记已投递"));
        assertTrue(actions.get(0).status.equals("submitted"));
        assertTrue(actions.get(0).nextStep.equals("prepare_interview_if_replied"));
        assertTrue(actions.get(1).label.equals("忽略"));
        assertTrue(actions.get(1).status.equals("ignored"));
    }

    @Test
    public void rendersEmptyStateWhenNoCareerDataExists() {
        CareerBoardResult board = new CareerBoardResult(List.of(), List.of(), List.of(), List.of());

        List<String> cards = CareerBoardPresenter.cards(board);

        assertTrue(cards.get(0).contains("还没有求职数据"));
        assertTrue(cards.get(0).contains("先让 Nomi 读取简历或一个 JD"));
    }
}

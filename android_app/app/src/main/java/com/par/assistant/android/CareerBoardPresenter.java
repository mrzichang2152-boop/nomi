package com.par.assistant.android;

import java.util.ArrayList;
import java.util.List;

final class CareerBoardPresenter {
    private CareerBoardPresenter() {
    }

    static List<String> cards(CareerBoardResult board) {
        List<String> cards = new ArrayList<>();
        if (board == null || (
                board.profiles.isEmpty()
                        && board.opportunities.isEmpty()
                        && board.resumeVersions.isEmpty()
                        && board.applications.isEmpty()
        )) {
            cards.add("还没有求职数据\n先让 Nomi 读取简历或一个 JD，它会把岗位、匹配评分、简历草案和申请状态放到这里。");
            return cards;
        }

        if (!board.profiles.isEmpty()) {
            CareerProfile profile = board.profiles.get(0);
            cards.add(
                    "职业画像\n"
                            + blankFallback(profile.headline, "待补充职业画像") + "\n"
                            + "目标：" + joinOr(profile.targetRoles, "待确认") + "\n"
                            + "技能：" + joinOr(profile.skills, "待确认")
            );
        }

        for (JobOpportunity opportunity : board.opportunities) {
            StringBuilder card = new StringBuilder();
            card.append(blankFallback(opportunity.title, "未命名岗位"));
            if (!opportunity.company.isEmpty()) {
                card.append(" · ").append(opportunity.company);
            }
            card.append("\n").append(opportunity.statusLine());
            if (!opportunity.location.isEmpty()) {
                card.append("\n地点：").append(opportunity.location);
            }
            if (!opportunity.requirements.isEmpty()) {
                card.append("\n要求：").append(joinOr(opportunity.requirements, ""));
            }
            ResumeVersion resume = firstResumeForJob(board.resumeVersions, opportunity.id);
            if (resume != null) {
                card.append("\n简历草案：").append(resume.status);
            }
            JobApplicationState application = firstApplicationForJob(board.applications, opportunity.id);
            if (application != null) {
                card.append("\n申请状态：").append(applicationStatusLabel(application.status));
                if (!application.nextStep.isEmpty()) {
                    card.append("\n下一步：").append(application.nextStep);
                }
            }
            cards.add(card.toString());
        }

        if (board.opportunities.isEmpty()) {
            for (JobApplicationState application : board.applications) {
                cards.add("申请状态\n" + application.statusLine());
            }
        }
        return cards;
    }

    static List<CareerBoardAction> actions(CareerBoardResult board) {
        List<CareerBoardAction> actions = new ArrayList<>();
        if (board == null) return actions;
        for (JobApplicationState application : board.applications) {
            if ("ignored".equals(application.status) || "submitted".equals(application.status)) {
                continue;
            }
            actions.add(
                    new CareerBoardAction(
                            application.id,
                            "标记已投递",
                            "submitted",
                            "submitted",
                            "prepare_interview_if_replied",
                            "用户在 Android 求职看板中标记已投递"
                    )
            );
            actions.add(
                    new CareerBoardAction(
                            application.id,
                            "忽略",
                            "ignored",
                            "ignored",
                            "none",
                            "用户在 Android 求职看板中忽略该机会"
                    )
            );
        }
        return actions;
    }

    private static ResumeVersion firstResumeForJob(List<ResumeVersion> resumes, String jobId) {
        for (ResumeVersion resume : resumes) {
            if (resume.targetJobId.equals(jobId)) return resume;
        }
        return null;
    }

    private static JobApplicationState firstApplicationForJob(List<JobApplicationState> applications, String jobId) {
        for (JobApplicationState application : applications) {
            if (application.jobId.equals(jobId)) return application;
        }
        return null;
    }

    private static String applicationStatusLabel(String status) {
        if ("blocked_until_delegated_grant".equals(status)) return "等待授权";
        if ("ready_for_confirmation".equals(status)) return "等待确认";
        if ("submitted".equals(status)) return "已投递";
        return blankFallback(status, "已记录");
    }

    private static String blankFallback(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }

    private static String joinOr(List<String> values, String fallback) {
        if (values == null || values.isEmpty()) return fallback;
        return String.join("、", values);
    }
}

final class CareerBoardAction {
    final String applicationId;
    final String label;
    final String status;
    final String stage;
    final String nextStep;
    final String userNote;

    CareerBoardAction(String applicationId, String label, String status, String stage, String nextStep, String userNote) {
        this.applicationId = applicationId == null ? "" : applicationId;
        this.label = label == null ? "" : label;
        this.status = status == null ? "" : status;
        this.stage = stage == null ? "" : stage;
        this.nextStep = nextStep == null ? "" : nextStep;
        this.userNote = userNote == null ? "" : userNote;
    }
}

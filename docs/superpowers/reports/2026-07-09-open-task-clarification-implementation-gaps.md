# Open Task Clarification Gate Implementation Notes

## 目标

复杂开放式任务（例如“帮我做一个 PPT”）在目标不清晰时，必须先和用户澄清；目标清晰后才交给 OpenCode 执行。OpenCode 执行过程中如果需要补充信息，也必须暂停并通过对话向用户确认，不能编造、不能静默失败、不能悄悄跳过。

## 已完成

- HTTP `/api/chat` 已接入 open task clarification gate。
  - 泛泛的 PPT 请求会停在 `waiting_for_human_input`。
  - 用户补充“普通人、10 页、科普、类比”等信息后，会恢复同一个 long-tail task，并生成 `requirements_contract`。
- WebSocket `/ws` 实时通道已接入同样的 clarification gate。
  - 不再绕过 HTTP 逻辑直接创建 OpenCode 任务。
  - 澄清回复走同一个 task，不进入普通聊天模型。
- OpenCode worker 已支持 `awaiting_user_input`。
  - 执行器需要补信息时会写入 `human_input.requested`。
  - 已有部分产出会写入任务 memory，任务不会被误标为 blocked。
- 重启恢复已补最小闭环。
  - 内存中找不到 pending task 时，会从 `long_tail_task_runs + long_tail_human_inputs` 查 waiting human input，再通过 event log `recover_task()` 恢复。
- Android 客户端已避免澄清任务触发产物轮询。
  - `waiting_user` / `waiting_for_human_input` 的 task 不再返回 `taskRunId` 给 artifact polling。
- 解析改进。
  - “做一个 PPT 让普通人可以理解 LLM 工作原理”会识别为可执行：受众普通人、深度科普、默认 10 页。
  - “AI 生成视频原理 PPT，可以用来讲解”仍会询问受众和深度。
- 可见文案与执行合约已对齐。
  - 已由 `requirements_contract` 明确或默认化的字段（例如目标听众、期望页数、PPT 用途）不会再被 `opencode_artifact_task_answer()` 错误展示为缺口。
  - HTTP/WebSocket 返回给客户端的 `task.requirements_contract` 已与 OpenCode plan 保持一致，避免真机端无法知道任务目标合约。

## 本轮验证

- `python3 -m pytest runtime_api/tests/test_open_task_clarification.py ... runtime_api/tests/test_opencode_artifact_worker.py::test_opencode_worker_pauses_when_executor_requests_user_input -q`
  - 15 passed。
- `gradle -p android_app testDebugUnitTest --tests com.par.assistant.android.AssistantApiClientTest.chatDoesNotPollArtifactsForClarificationTask --tests com.par.assistant.android.RealtimeClientTest.parsesStreamingChatDoneWithoutTaskRunIdForClarificationTask`
  - BUILD SUCCESSFUL。
- 云服务器冒烟发现并修复：
  - 首次部署后，明确请求“帮我做一个 ppt 让普通人可以理解 llm 的工作原理”已经进入 OpenCode，但回复仍显示“目标听众、期望页数”缺口。
  - 根因：OpenCode plan 过滤了合约已满足字段，但用户可见回答仍直接读取原始 `evidence_pack.missing_evidence`。
  - 已补测试并修复为统一使用合约过滤后的缺口，同时补齐客户端返回体中的 `requirements_contract`。
- 真机冒烟验证：
  - 已重新安装 Android debug APK，并在真机 `DQYTCYFMO7VSEAJB` 打开悬浮球对话框。
  - 通过真机悬浮窗发送英文模糊任务 `make a ppt about ai video generation for presentation` 后，服务端返回澄清问题，而不是直接拒绝或直接进入 OpenCode。
  - 真机实际可见回复为：先确认 PPT 面向普通人、学生、客户还是技术团队，以及偏科普还是偏技术原理；未指定时按普通人、10 页、科普风处理。
  - 这验证了真机端的第一步 clarification gate 生效。
- 针对真机自动化验收补齐英文澄清解析：
  - 英文补充 `ordinary people, 10 pages, popular science style, use analogies` 现在可以合并到同一个 pending task。
  - 合约会解析为受众普通人、10 页、科普、使用类比，不会继续卡在澄清问题。
- 云服务器二次冒烟验证：
  - 线上容器内 `/api/chat` 使用正确鉴权头 `X-Par-Password` 后验证通过。
  - 第一次发送“帮我做一个 AI 生成视频原理的 PPT 可以用来讲解”：返回 `waiting_user / waiting_for_human_input`，并追问受众与深度。
  - 第二次在同一个 `conversation_id` 发送英文补充：返回 `running / select_step`，同一 task 进入 OpenCode，`requirements_contract` 为普通人、10 页、科普、多用类比、主题 AI 生成视频原理。
- 云服务器 worker 恢复问题定位并修复：
  - 现象：HTTP 进程在用户补充澄清后已经得到可执行合约，但 worker 仍从旧 event log 恢复到 `clarification_gate`，随后把任务标记 blocked。
  - 根因：`resume_open_task_clarification_task()` 只更新了 HTTP 进程内存，没有把新的 `route.decided` / `plan.proposed` / `plan.validated` / `checkpoint.saved` 写入 `long_tail_task_events`。worker 是独立进程，只能从 Postgres events 恢复，所以看不到 plan v2。
  - 修复：澄清补充变成 executable 后，会持久化 plan v2 和 checkpoint；worker 恢复时能从 `select_step` 继续，而不是回到 `clarification_gate`。
  - 回归测试：`test_resumed_clarification_persists_executable_plan_for_worker_recovery` 覆盖“新 worker 从 event log 恢复后继续执行”的场景。
- 云服务器 API 级完整产物验证：
  - 同一 `conversation_id` 下先触发澄清，再补充“ordinary people, 10 pages, popular science style, use analogies”。
  - 任务 `lta_25f319895ba944108d25ea4ae008a415` 最终 `completed / delivered`。
  - 产物 `artifact_f99b16b7fd0c4d39b9cf1efb8f79867f`：`AI_生成视频原理的_PPT_可以用来讲解.pptx`，`verification_status=verified`。
- 真机完整路径验证：
  - 真机 `DQYTCYFMO7VSEAJB` 发送 `make a ppt about AI video generation for presentation 0709b`。
  - Nomi 先返回澄清问题，没有直接拒绝，也没有直接交给 OpenCode。
  - 真机继续发送 `ordinary people, 6 pages, popular science, use analogies`。
  - 同一任务 `lta_e80d05af96d34810a9ef125b0149f60e` 从 `select_step` 进入执行，最终 `completed / delivered`。
  - 产物 `artifact_168dcd3348c94c13ba21928623d6e941`：`AI_video_generation_for_presentation_0709b.pptx`，`verification_status=verified`。
  - 真机悬浮窗显示“文件已准备好 / PPTX · 已校验 / 点击下载”。
  - 点击下载后，真机显示“已开始下载 / 已保存到系统下载目录”，服务端日志出现 `/api/artifacts/artifact_168dcd3348c94c13ba21928623d6e941/download` 200。
  - 设备 `/sdcard/Download` 中确认存在 `AI_video_generation_for_presentation_0709b.pptx`。

## 仍需线上/真机验证

- 已部署到云服务器并完成 API 与真机完整链路冒烟：
  - vague task -> 澄清问题；（已在真机验证）
  - 用户补充目标 -> 同 task 进入 OpenCode；（已在真机验证）
  - OpenCode 生成真实文件 -> 下载链接可点可下载；（已在真机验证，且确认文件落到 `/sdcard/Download`）
- 尚未用真实 OpenCode 执行器验证 `awaiting_user_input` 的二次澄清交互。
- 尚未验证服务重启后，真机继续补充信息能从 Postgres event log 恢复同一个 task。
- 尚未验证 Android UI 是否需要额外展示 clarification 状态或“等待用户补充”的标识；当前只保证不会错误轮询产物。
- 真机自动化输入仍存在限制：
  - 当前红米 ROM 上 `adb shell input text` 无法可靠输入中文，`cmd clipboard` 也不可用。
  - 因此中文补充澄清这一步目前已通过线上 API UUID 会话验证；英文补充澄清已补解析能力，下一步可用于真机自动化跑完整路径。

## 后续建议

1. 构造 OpenCode 执行中途主动要求补充信息的真实用例，验证 `awaiting_user_input` 能暂停、向真机发问、用户补充后继续同一 task。
2. 在 `waiting_for_human_input` 状态重启后端和 worker，再从真机补充信息，验证 Postgres event log 恢复链路。
3. 设计 Android clarification 状态展示，避免用户只看到普通聊天气泡而不知道任务正在等待补充。
4. 后续若要自动化中文真机输入，需要换用支持 ADB IME/剪贴板的输入方案；当前红米 ROM 的 `adb shell input text` 和 `cmd clipboard` 都不能稳定输入中文。

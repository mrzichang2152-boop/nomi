# Nomi Pipeline 真实环境验收审计报告

日期：2026-06-18

结论先写清楚：**现有 27 条 pipeline 不能宣称已经全部在真实账号环境验收无误。**

用户指出的问题成立：目前用户还没有完成 WhatsApp、Gmail、Telegram 等真实账号登录，因此这些渠道的真实消息采集、真实邮件读取、真实聊天读取、真实账号状态下的主动建议闭环都没有被端到端验收。此前报告中出现的“通过”，只能解释为 **API contract / dry-run / 合成数据 / 真机 UI 层级通过**，不等于真实账号链路通过。

## 本次已修复

- 账号连接页标题已从“工具目录”改为“账号连接”。
- 本地回归测试覆盖标题一致性：`test_account_connection_view_title_matches_settings_entry`。
- 已部署到线上 `http://206.119.171.141`。
- Android 真机从主入口重新打开完整工作台后，账号页标题也已显示为“账号连接”。旧 WebView 会话曾短暂保留“工具目录”，重启工作台后消失。

验证证据：

```bash
python3 -m pytest runtime_api/tests/test_static_workbench_agenda_tab.py::test_account_connection_view_title_matches_settings_entry runtime_api/tests/test_auth_and_model.py::test_tool_catalog_returns_high_frequency_tools_with_permission_levels runtime_api/tests/test_pipeline_actions.py::test_account_login_pipeline_resolves_social_browser_login_urls -q
# 结果：3 passed in 0.38s

curl -sS -H 'x-par-password: par-dev' http://206.119.171.141/health
# 结果：{"status":"ok"}

curl -sS -H 'x-par-password: par-dev' http://206.119.171.141/static/index.html | rg -n '<h2>账号连接</h2>|<h2>工具目录</h2>|<strong>账号连接</strong>'
# 结果：
# 51:              <strong>账号连接</strong>
# 190:              <h2>账号连接</h2>

adb shell uiautomator dump /sdcard/nomi-account-title.xml
adb pull /sdcard/nomi-account-title.xml /tmp/nomi-account-title.xml
rg -n "账号连接|工具目录" /tmp/nomi-account-title.xml
# 结果包含：
# text="账号连接" resource-id="" class="android.widget.TextView"
# 未出现账号页标题 text="工具目录"
```

## 验收等级定义

后续报告必须使用以下等级，不能再只写“通过”：

| 等级 | 含义 |
| --- | --- |
| `REAL_E2E_VERIFIED` | 真实账号、真实外部页面或真实设备事件端到端通过，有 trace id、源事件 id、数据库写入、UI 结果或截图证据。 |
| `DEVICE_UI_VERIFIED` | Android 真机 UI 可访问、可点击、可显示，但不代表外部账号数据真实可读。 |
| `API_CONTRACT_VERIFIED` | 线上 API 或 pipeline dry-run 输出合理，证明路由、slots、门禁、草稿结构正确。 |
| `SYNTHETIC_DATA_VERIFIED` | 使用合成事件、fixture 或测试数据验证逻辑，不代表真实账号链路。 |
| `NOT_VERIFIED` | 尚未验收。 |
| `BLOCKED` | 受真实账号登录、provider 授权、外部服务或设备状态阻塞。 |

## 当前真实验收总览

| 范围 | 当前状态 | 说明 |
| --- | --- | --- |
| 线上服务健康 | `REAL_E2E_VERIFIED` | `/health` 返回 `{"status":"ok"}`。 |
| Web 工作台静态资源 | `REAL_E2E_VERIFIED` | 线上 `index.html` 已能检索到“账号连接”标题。 |
| Android 真机基础对话 UI | `DEVICE_UI_VERIFIED` | 之前确认真机可打开悬浮窗并发送基础消息；但不等于所有 pipeline 真机完成。 |
| 账号连接页入口 | `API_CONTRACT_VERIFIED` + 部分 `DEVICE_UI_VERIFIED` | 工具目录/账号连接入口可见；标题已修正。逐渠道真实登录后返回、读取状态仍未验收。 |
| Gmail 真实邮件采集 | `BLOCKED` | 真实 Gmail 未完成可用授权/登录链路验收。不能宣称真实 Gmail 邮件已采集成功。 |
| WhatsApp 真实聊天采集 | `BLOCKED` | WhatsApp Web 未完成真实登录后消息读取验收。不能宣称 WhatsApp 对话采集成功。 |
| Telegram 真实聊天采集 | `BLOCKED` | Telegram Web 未完成真实登录后消息读取验收。不能宣称 Telegram 对话采集成功。 |
| LinkedIn 登录/DOM 自动化 | `BLOCKED` | 未完成真实账号登录、找岗位、加人、私信、Apply/Submit 的真实 dry-run UI 验收。 |
| 外部真实副作用 | `NOT_VERIFIED` | 邮件发送、WhatsApp 发送、短信、电话、付款、打车、购物、Apply/Submit 都没有执行真实副作用；当前应保持 dry-run/确认卡。 |

## 27 条 Pipeline 逐项审计

| 编号 | pipeline | 当前最高可信等级 | 是否真实账号端到端无误 | 审计结论 |
| --- | --- | --- | --- | --- |
| P01 | `event_ingestion_pipeline` | `SYNTHETIC_DATA_VERIFIED` | 否 | 事件规范化可用，但 Gmail/WhatsApp/Telegram 的真实新消息注入未完成。 |
| P02 | `memory_write_pipeline` | `SYNTHETIC_DATA_VERIFIED` | 否 | 合成事件写记忆逻辑可测；真实渠道事件写入长期记忆未验收。 |
| P03 | `context_pack_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 作用域拼接和近期对话策略可测；真实账号数据召回未验收。 |
| P04 | `personal_search_pipeline` | `API_CONTRACT_VERIFIED` | 否 | fixture/合成记忆搜索可测；真实 Gmail/WhatsApp/Telegram 记忆搜索未验收。 |
| P05 | `chat_response_pipeline` | 部分 `DEVICE_UI_VERIFIED` | 否 | 真机基础对话可发起；是否能结合真实账号上下文回答未验收。 |
| P06 | `reply_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 回复草稿和确认门禁可测；真实 WhatsApp/Telegram/邮件回复未发送也未端到端验收。 |
| P07 | `email_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 邮件草稿结构可测；真实 Gmail 读取、草稿生成、发送门禁未端到端验收。 |
| P08 | `agenda_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 相对时间解析已用合成输入验证；真实聊天/邮件自动成日程未验收。 |
| P09 | `task_todo_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 待办结构可测；真实私有消息自动生成待办未验收。 |
| P10 | `proactive_suggestion_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 主动建议结构可测；真实渠道触发到 Android 气泡未完整验收。 |
| P11 | `route_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 路线查询计划保持 read-only；真实地图 provider 未接通验收。 |
| P12 | `ride_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 缺 pickup 时能停住；真实 Uber/打车 provider 未验收。 |
| P13 | `shopping_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 比价/购物计划结构可测；真实 Amazon/电商 provider 未验收。 |
| P14 | `payment_bill_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 付款门禁可测；真实账单读取和付款 provider 未验收。 |
| P15 | `contact_relationship_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 关系信号结构可测；真实联系人和真实多渠道关系图谱未验收。 |
| P16 | `document_file_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 文档摘要/读取结构可测；真实 Google Drive/Docs provider 未验收。 |
| P17 | `career_profile_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 简历文本合成输入可生成职业画像；真实简历库、多版本 UI、真实 LinkedIn 资料未端到端验收。 |
| P18 | `job_discovery_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 岗位结构化可测；真实 LinkedIn/ATS 浏览器找岗位未验收。 |
| P19 | `job_fit_scoring_pipeline` | `API_CONTRACT_VERIFIED` | 否 | JD + 简历 fixture 匹配评分可测；真实岗位与真实简历未验收。 |
| P20 | `resume_tailoring_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 简历修改草稿可测；真实导出、逐段编辑、版本管理未完整验收。 |
| P21 | `cover_letter_pipeline` | `API_CONTRACT_VERIFIED` | 否 | Cover Letter 草稿可测；真实 Gmail/Docs 写入未验收。 |
| P22 | `outreach_message_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 外联草稿和确认卡可测；真实 LinkedIn/Gmail/WhatsApp 发送未验收。 |
| P23 | `job_application_pipeline` | `API_CONTRACT_VERIFIED` | 否 | Apply/Submit 被授权门禁拦住是正确的；真实 ATS 提交未验收，也不应无确认执行。 |
| P24 | `application_tracking_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 求职阶段跟踪结构可测；真实邮件/LinkedIn 回执驱动状态变更未验收。 |
| P25 | `interview_prep_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 基于 fixture JD/简历生成面试准备可测；真实面试邮件、真实岗位数据未验收。 |
| P26 | `account_login_pipeline` | `API_CONTRACT_VERIFIED` + 部分 `DEVICE_UI_VERIFIED` | 否 | API 能路由 Gmail/WhatsApp/Telegram/LinkedIn 登录入口；真实登录完成、关闭返回账号列表、登录状态持久化仍未完成验收。 |
| P27 | `governance_audit_pipeline` | `API_CONTRACT_VERIFIED` | 否 | 高风险动作解释/门禁结构可测；真实高风险工具链路审计未验收。 |

## 必须纠正的表述

以下表述以后不能再直接使用：

- “27 条 pipeline 都已经真实环境验收通过。”
- “WhatsApp/Gmail/Telegram 注入已经真实验收无误。”
- “主动建议真实链路已经完成。”

更准确的表述应是：

- “27 条 pipeline 多数完成 API contract / dry-run / synthetic 数据验证。”
- “账号连接入口和部分 Android UI 经过真机验证。”
- “Gmail/WhatsApp/Telegram 真实账号登录后的采集、记忆写入、主动建议和对话召回仍处于 BLOCKED，必须等真实账号登录后重新验收。”

## 后续真实验收必须满足的证据

每个真实渠道至少要拿到以下证据，才能从 `BLOCKED` 或 `API_CONTRACT_VERIFIED` 升级为 `REAL_E2E_VERIFIED`：

1. 真实账号登录状态截图或可审计状态，不要求暴露密码。
2. 真实来源事件 ID，例如 Gmail message id、WhatsApp chat/message id、Telegram message id。
3. 服务端 ingestion trace id。
4. 数据库写入证据：raw event、memory item、agenda item 或 proactive suggestion。
5. pipeline execution 记录，包含 `pipeline_id`、steps、slots、status。
6. Android 真机 UI 结果：消息气泡、对话回答、日程/建议卡片或账号状态页面。
7. 如果涉及外部副作用，必须有确认卡和 dry-run 证明；未明确确认前不能真实发送、付款、投递。

## 下一步建议

1. 先完成 Gmail、WhatsApp、Telegram 的真实登录。
2. 每个渠道各触发一条可控测试消息或测试邮件。
3. 跑 `P01 -> P02 -> P03 -> P05` 验证“采集、记忆、上下文、回答”闭环。
4. 跑 `P08 -> P10` 验证“自动日程、主动建议、Android 气泡”闭环。
5. 再跑 `P26` 逐渠道登录页打开、关闭、返回账号列表、登录状态显示。
6. 求职链路先用真实简历 + 真实 JD 做 `P17-P25`，LinkedIn/ATS 自动化仍保持 dry-run 和每日限额。

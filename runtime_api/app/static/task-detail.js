const taskPasswordKey = "par-password";
const taskSummary = document.querySelector("#taskSummary");
const taskSteps = document.querySelector("#taskSteps");
const taskEvidence = document.querySelector("#taskEvidence");
const taskArtifacts = document.querySelector("#taskArtifacts");
const taskError = document.querySelector("#taskError");
const taskSubtitle = document.querySelector("#taskSubtitle");

function taskIdFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[1] || "");
}

function taskPassword() {
  return localStorage.getItem(taskPasswordKey) || "";
}

async function apiGetJson(path) {
  const response = await fetch(path, {
    headers: {
      "x-par-password": taskPassword(),
    },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function fetchTaskDetail(taskId = taskIdFromPath()) {
  if (!taskId) throw new Error("missing task id");
  const [detail, artifacts] = await Promise.all([
    apiGetJson(`/api/tasks/${encodeURIComponent(taskId)}`),
    apiGetJson(`/api/tasks/${encodeURIComponent(taskId)}/artifacts`),
  ]);
  return {
    ...detail,
    artifacts: artifacts.artifacts || [],
  };
}

function renderTaskDetail(data) {
  const task = data.task || {};
  document.title = `${task.task_run_id || "Task"} · Nomi Task Detail`;
  taskSubtitle.textContent = task.title || task.task_run_id || "任务详情";
  renderSummary(task);
  renderSteps(data.steps || []);
  renderEvidence(data.evidence_links || []);
  renderArtifacts(data.artifacts || []);
}

function renderSummary(task) {
  const rows = [
    ["任务 ID", task.task_run_id],
    ["状态", task.status],
    ["Pipeline", task.pipeline_id],
    ["类型", task.task_type],
    ["风险", task.risk_permission],
    ["创建时间", task.created_at],
    ["更新时间", task.updated_at],
  ];
  taskSummary.replaceChildren(
    ...rows.map(([label, value]) => {
      const fragment = document.createDocumentFragment();
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value || "-";
      fragment.append(dt, dd);
      return fragment;
    })
  );
}

function renderSteps(steps) {
  if (!steps.length) {
    renderEmpty(taskSteps, "暂无步骤记录");
    return;
  }
  taskSteps.replaceChildren(
    ...steps.map((step) =>
      taskListItem({
        title: `${step.step_order}. ${step.step_name || "未命名步骤"}`,
        meta: `${step.status || "unknown"} · attempts ${step.attempt_count || 0}`,
        body: step.reasoning_summary || compactJson(step.output_json || step.input_json || {}),
      })
    )
  );
}

function renderEvidence(evidenceLinks) {
  if (!evidenceLinks.length) {
    renderEmpty(taskEvidence, "暂无证据链接");
    return;
  }
  taskEvidence.replaceChildren(
    ...evidenceLinks.map((item) =>
      taskListItem({
        title: item.evidence_id || "evidence",
        meta: `${item.source || "unknown"} · ${item.evidence_type || "evidence"} · confidence ${item.confidence ?? 0}`,
        body: [item.contact_or_actor, item.used_for].filter(Boolean).join(" / "),
      })
    )
  );
}

function renderArtifacts(artifacts) {
  if (!artifacts.length) {
    renderEmpty(taskArtifacts, "暂无交付文件");
    return;
  }
  taskArtifacts.replaceChildren(
    ...artifacts.map((artifact) => {
      const item = taskListItem({
        title: artifact.filename || artifact.artifact_id || "artifact",
        meta: `${(artifact.artifact_type || "file").toUpperCase()} · ${artifact.verification_status || "pending"}`,
        body: artifact.mime_type || "",
      });
      if (artifact.download_url) {
        const link = document.createElement("a");
        link.className = "task-download-link";
        link.href = artifact.download_url;
        link.textContent = "下载文件";
        item.append(link);
      }
      return item;
    })
  );
}

function taskListItem({ title, meta, body }) {
  const article = document.createElement("article");
  article.className = "task-list-item";
  const strong = document.createElement("strong");
  strong.textContent = title || "-";
  const small = document.createElement("small");
  small.textContent = meta || "";
  const paragraph = document.createElement("p");
  paragraph.textContent = body || "";
  article.append(strong, small, paragraph);
  return article;
}

function renderEmpty(node, message) {
  const empty = document.createElement("p");
  empty.className = "task-detail-empty";
  empty.textContent = message;
  node.replaceChildren(empty);
}

function compactJson(value) {
  try {
    return JSON.stringify(value, null, 2).slice(0, 600);
  } catch {
    return "";
  }
}

function showTaskError(error) {
  taskError.classList.remove("hidden");
  taskError.textContent = `加载任务详情失败：${error.message || error}`;
}

fetchTaskDetail()
  .then(renderTaskDetail)
  .catch(showTaskError);

window.NomiTaskDetail = { fetchTaskDetail, renderTaskDetail };

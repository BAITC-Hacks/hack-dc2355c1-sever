const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const wsUrl = (path) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

function actionPill(d) {
  if (d.action === "handoff") return `<span class="pill danger">оператор</span>`;
  if (d.action === "clarify") return `<span class="pill warn">переспрос</span>`;
  return `<span class="pill">${esc(d.scenario_id)}</span>`;
}

function stagesText(stages) {
  return Object.entries(stages || {}).map(([k, v]) => `${k} ${Math.round(v)}мс`).join(" · ");
}

function traceHtml(t) {
  const d = t.decision;
  const alts = (d.alternatives || []).map((a) => `${esc(a.scenario_id)} ${(a.confidence * 100).toFixed(0)}%`).join(", ");
  return `
    <div>${actionPill(d)} <b>${(d.confidence * 100).toFixed(0)}%</b> · путь: <span class="mono">${esc(t.path)}</span> · язык: ${esc(d.language)}
      ${d.secondary_scenario_id ? ` · вторая тема: <span class="pill warn">${esc(d.secondary_scenario_id)}</span>` : ""}</div>
    <div>${esc(d.reasoning)}</div>
    ${alts ? `<div>альтернативы: ${alts}</div>` : ""}
    ${Object.keys(d.params || {}).length ? `<div class="mono">params: ${esc(JSON.stringify(d.params))}</div>` : ""}
    <div class="mono stages">${stagesText(t.stages_ms)}</div>`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const wsUrl = (path) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

const topConf = (d) => (d.scenarios && d.scenarios[0] ? d.scenarios[0].confidence : 0);
const pctStr = (x) => `${Math.round((x || 0) * 100)}%`;

const ACTION_LABELS = {
  clarify: ["warn", "переспрос"], handoff: ["danger", "оператор"], out_of_scope: ["warn", "вне тематики"],
  goodbye: ["", "прощание"], continue: ["", "продолжение"],
};

function actionPill(d) {
  const [cls, label] = ACTION_LABELS[d.action] || ["", "сценарий"];
  return `<span class="pill ${cls}">${label}</span>`;
}

function stagesText(stages) {
  return Object.entries(stages || {}).map(([k, v]) => `${k} ${Math.round(v)}мс`).join(" · ");
}

function traceHtml(t) {
  const d = t.decision;
  const hits = (d.scenarios || []).map((s) => `<span class="pill">${esc(s.scenario_id)} ${pctStr(s.confidence)}</span>`).join("");
  const alts = (d.alternatives || []).map((a) => `${esc(a.scenario_id)} ${pctStr(a.confidence)}`).join(", ");
  const reasons = (d.scenarios || []).filter((s) => s.reason).map((s) => `${esc(s.scenario_id)}: ${esc(s.reason)}`).join("; ");
  return `
    <div>${actionPill(d)} ${hits} · путь <span class="mono">${esc(t.path)}</span> · язык ${esc(d.language)} → ответ ${esc(d.reply_language)}</div>
    <div>${esc(d.reasoning)}</div>
    ${reasons ? `<div>${reasons}</div>` : ""}
    ${alts ? `<div>альтернативы: ${alts}</div>` : ""}
    <div class="mono">политика: ${esc(d.policy_note)}</div>
    ${Object.keys(d.slots || {}).length ? `<div class="mono">слоты: ${esc(JSON.stringify(d.slots))}</div>` : ""}
    ${t.topic_queue && t.topic_queue.length ? `<div class="mono">стек тем: ${esc(t.topic_queue.join(" → "))}</div>` : ""}
    <div class="mono stages">${stagesText(t.stages_ms)}</div>`;
}

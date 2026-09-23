const rows = document.getElementById("rows");
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const ms = (x) => (x == null ? "—" : `${Math.round(x)} мс`);

function row(t) {
  const tr = document.createElement("tr");
  const lowConf = t.decision.confidence < 0.8 || t.decision.action !== "route";
  tr.innerHTML = `
    <td class="mono">${new Date(t.ts * 1000).toLocaleTimeString()}</td>
    <td class="mono">${esc(t.session_id)}#${t.turn}</td>
    <td>${esc(t.user_text)}</td>
    <td style="min-width:360px${lowConf ? ";background:var(--warn-bg)" : ""}">${traceHtml(t)}</td>
    <td>${esc(t.bot_text)}</td>`;
  return tr;
}

async function loadStats() {
  const s = await (await fetch("/api/stats")).json();
  const kpis = [
    ["Реплик", s.turns], ["Только быстрый путь", pct(s.fast_only_rate)], ["Эскалаций", pct(s.escalation_rate)],
    ["Переспросов", pct(s.clarify_rate)], ["Передач оператору", pct(s.handoff_rate)],
    ["Роутер p50", ms(s.router_ms_p50)], ["Роутер p95", ms(s.router_ms_p95)], ["Неуверенных", s.low_confidence],
  ];
  document.getElementById("kpis").innerHTML = kpis
    .map(([l, v]) => `<div class="card kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  const max = Math.max(1, ...Object.values(s.by_scenario));
  document.getElementById("byScenario").innerHTML = Object.entries(s.by_scenario)
    .map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${v}</td><td><span class="bar" style="width:${(v / max) * 200}px"></span></td></tr>`).join("");
}

async function init() {
  const traces = await (await fetch("/api/traces?limit=100")).json();
  traces.forEach((t) => rows.appendChild(row(t)));
  loadStats();
  const ws = new WebSocket(wsUrl("/ws/supervisor"));
  ws.onmessage = (ev) => { rows.prepend(row(JSON.parse(ev.data))); loadStats(); };
  ws.onclose = () => setTimeout(init, 2000);
}
init();

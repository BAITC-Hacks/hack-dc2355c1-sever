const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));
const wsUrl = path => (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + path;
const topConf = d => d?.scenarios?.[0]?.confidence || 0;
const pctStr = x => Math.round(Math.max(0, Math.min(1, Number(x) || 0))*100) + "%";
const h = key => esc(tr(key));
const ACTION_LABELS = {
  clarify: ["warn","переспрос"], handoff: ["danger","оператор"], out_of_scope: ["warn","вне тематики"],
  goodbye: ["","прощание"], continue: ["","продолжение"],
};
function actionPill(d) {
  const [tone,label] = ACTION_LABELS[d.action] || ["","сценарий"];
  return '<span class="pill ' + tone + '">' + h(label) + '</span>';
}
function jsonDetails(label,value) {
  if (value == null) return "";
  return '<details class="trace-data"><summary>' + h(label) + '</summary><pre>' + esc(JSON.stringify(value,null,2)) + '</pre></details>';
}
function actionStatus(a) {
  if (a.blocked) return ["danger","Заблокировано"];
  if (a.result?.error) return ["danger","Ошибка"];
  if (a.mode === "preview") return ["warn","Превью · не выполнено"];
  if (a.mode === "execute") return a.result == null ? ["warn","Выполнение · результат не получен"] : ["","Выполнено"];
  if (a.name === "complete_scenario") return ["","Сценарий завершён"];
  return a.result == null ? ["warn","Результат не получен"] : ["","Результат получен"];
}
function actionsHtml(actions) {
  if (!Array.isArray(actions) || !actions.length) return '<p class="trace-muted">' + h("В этом ходе действия не вызывались.") + '</p>';
  return '<ol class="trace-actions">' + actions.map(a => {
    const [tone,label] = actionStatus(a), error = a.result?.error;
    return '<li class="trace-action"><div class="trace-action-heading"><code>' + esc(a.name || tr("Действие")) +
      '</code><span class="pill ' + tone + '">' + h(label) + '</span>' +
      (a.guard || a.blocked ? '<span class="pill warn">' + h("Сработала защита") + '</span>' : '') + '</div>' +
      (a.guard || a.blocked ? '<p class="trace-notice">' + esc(a.guard || tr("Вызов запрещён для выбранного сценария.")) + '</p>' : '') +
      (error ? '<p class="trace-error">' + esc(error.code || tr("Ошибка действия")) + (error.message ? ': '+esc(error.message) : '') + '</p>' : '') +
      jsonDetails("Аргументы",a.args) + jsonDetails("Результат",a.result) + '</li>';
  }).join("") + '</ol>';
}
function scenarioHtml(hit,alternative=false) {
  const confidence = typeof hit.confidence === "number" && Number.isFinite(hit.confidence) ? Math.max(0,Math.min(1,hit.confidence)) : null;
  return '<div class="trace-scenario' + (alternative ? ' trace-alternative' : '') + '"><div class="trace-scenario-heading"><code>' +
    esc(hit.scenario_id || tr("Сценарий не указан")) + '</code><span class="trace-confidence">' +
    (confidence === null ? h("Уверенность не указана") : pctStr(confidence)) + '</span></div>' +
    (confidence === null ? '' : '<div class="trace-confidence-track" aria-hidden="true"><span style="width:' + Math.round(confidence*100) + '%"></span></div>') +
    (hit.reason ? '<p>' + esc(hit.reason) + '</p>' : '') + '</div>';
}
const STAGE_LABELS = {
  stt:"Распознавание речи", triage:"Нормализация", candidates:"Поиск кандидатов", router_fast:"Быстрый роутер",
  router_strong:"Основной роутер", policy:"Проверка решения", response:"Подготовка ответа",
};
function duration(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "—";
  return ms >= 1000 ? (ms/1000).toLocaleString(I18N.lang === "kk" ? "kk-KZ" : "ru-RU", {maximumFractionDigits:2}) + " " + tr("с") : Math.round(ms) + " " + tr("мс");
}
function timingsHtml(stages={}) {
  const valid = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const rows = Object.entries(stages).filter(([key,value]) => !["total","end_to_audio","parallel_executor"].includes(key) && valid(value));
  const max = Math.max(1,...rows.map(([,v]) => v));
  const summaries = [["end_to_audio","До первого аудио"],["total","Всего на сервере"]].filter(([key]) => valid(stages[key]));
  if (!rows.length && !summaries.length) return '<p class="trace-muted">' + h("Пока нет измерений") + '</p>';
  return '<div class="timing-summary">' + summaries.map(([key,label]) =>
    '<div class="timing-kpi"><span>' + h(label) + '</span><strong>' + esc(duration(stages[key])) + '</strong></div>').join("") +
    '</div>' + rows.map(([key,value]) => '<div class="timing-row"><span>' + esc(tr(STAGE_LABELS[key] || key)) +
      '</span><div class="timing-track" aria-hidden="true"><span style="width:' + (value/max*100).toFixed(2) +
      '%"></span></div><span class="timing-value">' + esc(duration(value)) + '</span></div>').join("") +
    (stages.parallel_executor ? '<p class="timing-note">' + h("Исполнитель работал параллельно с роутером") + '</p>' : '') +
    '<p class="timing-note">' + h("Этапы могут идти параллельно; их длительности не суммируются.") +
    (valid(stages.end_to_audio) ? ' ' + h("До отправки первого аудиофрагмента сервером.") : '') + '</p>';
}
function traceHtml(t) {
  const d=t.decision || {}, scenarios=Array.isArray(d.scenarios)?d.scenarios:[], alternatives=Array.isArray(d.alternatives)?d.alternatives:[];
  const languages={ru:"Русский",kk:"Қазақша",mixed:"Смешанный"};
  const paths={fast:"Быстрый",strong:"Основной","fast->strong":"Быстрый → основной",error:"Ошибка маршрутизации"};
  const context={client_id:t.client_id,active_scenario:t.active_scenario,topic_queue:t.topic_queue,candidates:t.candidates,slots:d.slots};
  const section = (label,content) => '<div class="trace-section"><h3>' + h(label) + '</h3>' + content + '</div>';
  return '<section class="trace-card"><div class="trace-heading"><strong>' + h("Решение по реплике") +
    (t.turn != null ? ' №'+esc(t.turn) : '') + '</strong>' + actionPill(d) + '</div>' +
    '<div class="trace-meta"><span>' + h("Путь") + ': ' + esc(tr(paths[t.path] || t.path || "Не указан")) +
    '</span><span>' + h("Язык") + ': ' + esc(tr(languages[d.language] || d.language || "Не определён")) +
    ' → ' + esc(tr(languages[d.reply_language] || d.reply_language || "Не указан")) + '</span></div>' +
    section("Сценарии и уверенность",'<div class="trace-scenarios">' +
      (scenarios.length ? scenarios.map(s=>scenarioHtml(s)).join("") : '<p class="trace-muted">'+h("Сценарий не выбран.")+'</p>') + '</div>') +
    section("Обоснование",'<p>'+esc(d.reasoning || tr("Обоснование пока не получено."))+'</p>' +
      (d.policy_note ? '<details class="trace-data"><summary>'+h("Политика")+'</summary><p>'+esc(d.policy_note)+'</p></details>' : '')) +
    section("Альтернативы",'<div class="trace-scenarios">' +
      (alternatives.length ? alternatives.map(a=>scenarioHtml(a,true)).join("") : '<p class="trace-muted">'+h("Роутер не указал альтернатив.")+'</p>')+'</div>') +
    section("Действия",actionsHtml(t.actions)) +
    (t.handoff_queue ? '<p class="trace-notice">'+h("Передача оператору")+': <code>'+esc(t.handoff_queue)+'</code></p>' : '') +
    section("Задержки",timingsHtml(t.stages_ms || {})) +
    jsonDetails("Контекст и слоты",context) + '</section>';
}

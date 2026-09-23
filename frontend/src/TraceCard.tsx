import type { Trace, TraceAction } from "./hooks/use-conversation";

const ACTION_LABELS: Record<string, [string, string]> = {
  route: ["сценарий", "scenario"], continue: ["продолжение", "scenario"], clarify: ["переспрос", "warn"],
  handoff: ["оператор", "bad"], out_of_scope: ["вне тематики", "warn"], goodbye: ["прощание", "good"],
};
// Этапы, которые идут параллельно или являются итогом, не рисуем полосками (иначе сумма «больше» реального времени).
const HIDDEN_STAGES = new Set(["total", "parallel_executor", "policy", "triage"]);
const pct = (x = 0) => `${Math.round(x * 100)}%`;
const ms = (x = 0) => `${Math.round(x)} мс`;

function actionChip(a: TraceAction) {
  const error = a.result && typeof a.result === "object" && "error" in a.result ? (a.result as { error: { code: string } }).error : null;
  const tone = a.guard ? "warn" : error ? "bad" : a.mode === "execute" ? "good" : "";
  const title = JSON.stringify({ args: a.args, result: a.result, guard: a.guard }, null, 1);
  return <span key={`${a.name}-${a.mode ?? ""}-${title.length}`} className={`chip ${tone}`} title={title}>
    {a.name}{a.mode ? `:${a.mode}` : ""}{error ? ` ✗ ${error.code}` : ""}
  </span>;
}

/** Решение роутера и работа исполнителя по одной реплике: сценарий, уверенность, альтернативы, действия, время. */
export function TraceCard({ trace, open = false }: { trace: Trace; open?: boolean }) {
  const d = trace.decision;
  const [label, tone] = ACTION_LABELS[d.action] ?? [d.action, ""];
  const stages = Object.entries(trace.stages_ms).filter(([k]) => !HIDDEN_STAGES.has(k));
  const longest = Math.max(1, ...stages.map(([, v]) => v));
  const guards = (trace.actions ?? []).filter(a => a.guard);
  return <details className="trace-card" open={open}>
    <summary>
      <span className={`chip ${tone}`}>{label}</span>
      {d.scenarios.map(s => <span key={s.scenario_id} className="chip scenario">{s.scenario_id} · {pct(s.confidence)}</span>)}
      <span className="chip alt">{d.language} → {d.reply_language}</span>
      {trace.stages_ms.end_to_audio != null && <span className="chip alt">до звука {ms(trace.stages_ms.end_to_audio)}</span>}
    </summary>
    {d.reasoning && <div className="reason">{d.reasoning}</div>}
    {!!d.alternatives?.length && <div className="trace-row"><b>альтернативы</b>
      {d.alternatives.map(a => <span key={a.scenario_id} className="chip alt">{a.scenario_id} · {pct(a.confidence)}</span>)}</div>}
    {d.policy_note && <div className="trace-row"><b>политика</b><span>{d.policy_note}</span></div>}
    {!!Object.keys(d.slots ?? {}).length && <div className="trace-row"><b>слоты</b>
      {Object.entries(d.slots).filter(([k]) => k !== "relative_dates").map(([k, v]) =>
        <span key={k} className="chip alt">{k}={typeof v === "string" ? v : JSON.stringify(v)}</span>)}</div>}
    {trace.client_id && <div className="trace-row"><b>клиент</b><span className="chip">{trace.client_id}</span></div>}
    {!!trace.actions?.length && <div className="trace-row"><b>действия</b>{trace.actions.map(actionChip)}</div>}
    {guards.map(a => <div key={`g-${a.name}`} className="trace-row"><b>защита</b><span>{a.guard}</span></div>)}
    {!!trace.topic_queue?.length && <div className="trace-row"><b>отложено</b>{trace.topic_queue.map(t => <span key={t} className="chip alt">{t}</span>)}</div>}
    {trace.handoff_queue && <div className="trace-row"><b>передано</b><span className="chip bad">{trace.handoff_queue}</span></div>}
    {!!stages.length && <div className="stage-bars">{stages.map(([k, v]) =>
      <div key={k} className="stage-bar"><span>{k}</span><i style={{ width: `${(v / longest) * 100}%` }} /><span>{ms(v)}</span></div>)}</div>}
  </details>;
}

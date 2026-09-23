import { useEffect, useState } from "react";
import { Activity, ArrowLeft, ArrowUpRight, RefreshCw, Search } from "lucide-react";
import { Header } from "./App";
import { Button } from "@/components/ui/button";
import { wsUrl, type Trace } from "./hooks/use-conversation";

type Stats = { turns: number; fast_only_rate: number; escalation_rate: number; handoff_rate: number; router_ms_p50: number | null; end_to_audio_p50: number | null; by_scenario: Record<string, number> };
const percent = (value: number) => `${Math.round(value * 100)}%`;
const millis = (value: number | null) => value == null ? "—" : `${Math.round(value)} мс`;
const labels: Record<string, string> = { route: "Сценарий", continue: "Продолжение", clarify: "Уточнение", handoff: "Оператор", goodbye: "Завершение", out_of_scope: "Вне тематики" };

export function Supervisor() {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState("");
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  const [generation, setGeneration] = useState(0);
  const [selected, setSelected] = useState<Trace | null>(null);
  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const loadStats = async () => {
      const response = await fetch("/api/stats", { signal: controller.signal });
      if (!response.ok) throw new Error("Не удалось загрузить статистику");
      const data = await response.json();
      if (!disposed) setStats(data);
    };
    const connect = () => {
      if (disposed) return;
      ws = new WebSocket(wsUrl("/ws/supervisor"));
      ws.onopen = () => { if (!disposed) { setLive(true); setError(""); } };
      ws.onmessage = event => {
        if (disposed) return;
        try {
          const trace = JSON.parse(event.data) as Trace;
          setTraces(items => [trace, ...items.filter(item => !(item.session_id === trace.session_id && item.turn === trace.turn))].slice(0, 200));
          void loadStats().catch(() => { if (!disposed) setError("Не удалось обновить статистику"); });
        } catch { setError("Получена некорректная трассировка"); }
      };
      ws.onclose = () => { if (!disposed) { setLive(false); retry = setTimeout(init, 2000); } };
    };
    const init = async () => {
      try {
        const response = await fetch("/api/traces?limit=200", { signal: controller.signal });
        if (!response.ok) throw new Error("Не удалось загрузить диалоги");
        const data = await response.json();
        if (disposed) return;
        setTraces(data); await loadStats(); connect();
      } catch { if (!disposed) setError("Сервер недоступен. Попробуйте обновить данные."); }
    };
    void init();
    return () => { disposed = true; controller.abort(); clearTimeout(retry); ws?.close(); };
  }, [generation]);
  const filtered = traces.filter(trace => `${trace.user_text} ${trace.bot_text} ${trace.session_id} ${trace.decision.scenarios.map(s => s.scenario_id).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  const metrics = stats ? [["Всего реплик", stats.turns], ["Быстрый маршрут", percent(stats.fast_only_rate)], ["Передано оператору", percent(stats.handoff_rate)], ["Роутер · p50", millis(stats.router_ms_p50)], ["До звука · p50", millis(stats.end_to_audio_p50)]] : [];
  return <div className="app-shell"><Header supervisor /><main className="dashboard">
    <div className="dashboard-top"><div><div className="eyebrow">ЦЕНТР УПРАВЛЕНИЯ</div><h1>Каждый диалог — <span>на виду.</span></h1><p>Маршрутизация, ответы и скорость в реальном времени.</p></div><Button variant="outline" onClick={() => { setLive(false); setGeneration(v => v + 1); }}><RefreshCw size={15} /> Обновить</Button></div>
    {error && <div role="alert" className="error-notice">{error}</div>}
    <section className="metrics" aria-label="Статистика">{metrics.length ? metrics.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong><Activity size={16} /></div>) : <p>Загружаем статистику…</p>}</section>
    <section className="traces-panel"><div className="panel-header"><h2>Лента обращений <span className={`live-badge ${live ? "is-live" : ""}`}><span className="small-dot" />{live ? "LIVE" : "OFFLINE"}</span></h2><label className="trace-search"><Search size={16} /><input aria-label="Поиск по диалогам" placeholder="Поиск по диалогам…" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
    <div className="table-scroll"><table><thead><tr><th>Время / сессия</th><th>Запрос клиента</th><th>Маршрут</th><th>Ответ ассистента</th><th><span className="sr-only">Подробности</span></th></tr></thead><tbody>{filtered.map(trace => <tr key={`${trace.session_id}-${trace.turn}`}><td><time>{new Date(trace.ts * 1000).toLocaleTimeString("ru-RU")}</time><small>{trace.session_id.slice(0, 8)} · #{trace.turn}</small></td><td>{trace.user_text}</td><td><span className={`route-badge ${trace.decision.action === "handoff" ? "route-warn" : ""}`}>{labels[trace.decision.action] || trace.decision.action}</span><small>{trace.decision.scenarios[0]?.scenario_id || trace.path}</small></td><td><div className="table-answer">{trace.bot_text}</div></td><td><button className="detail-button" aria-label={`Подробности реплики ${trace.turn} сессии ${trace.session_id}`} onClick={() => setSelected(trace)}><ArrowUpRight size={18} /></button></td></tr>)}</tbody></table></div>
    {!filtered.length && <div className="empty-state"><MessageIcon /><h3>{query ? "Ничего не найдено" : "Здесь появятся диалоги"}</h3><p>{query ? "Попробуйте другой запрос." : "Начните разговор с ассистентом, чтобы увидеть его маршрут."}</p><a href="/">Перейти к ассистенту <ArrowUpRight size={14} /></a></div>}
    <div className="panel-footer">Показано {filtered.length} из {traces.length} последних реплик</div></section>
    {stats && Object.keys(stats.by_scenario).length > 0 && <section className="scenario-panel"><h2>Популярные сценарии</h2>{Object.entries(stats.by_scenario).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => <div className="scenario-row" key={name}><span>{name}</span><div><i style={{ width: `${count / Math.max(...Object.values(stats.by_scenario)) * 100}%` }} /></div><strong>{count}</strong></div>)}</section>}
  </main>
  {selected && <div className="detail-overlay" onClick={() => setSelected(null)}><section className="trace-detail" role="dialog" aria-modal="true" aria-label="Подробности маршрута" onClick={event => event.stopPropagation()} onKeyDown={event => { if (event.key === "Escape") setSelected(null); }}><Button autoFocus variant="ghost" onClick={() => setSelected(null)}><ArrowLeft size={16} /> Назад к обращениям</Button><h2>Реплика #{selected.turn}</h2><p className="detail-query">{selected.user_text}</p><h3>Ответ</h3><p>{selected.bot_text}</p><h3>Решение маршрутизатора</h3><p>{selected.decision.reasoning}</p><div className="trace-tags"><span>{selected.path}</span><span>{selected.decision.language} → {selected.decision.reply_language}</span>{selected.decision.scenarios.map(s => <span key={s.scenario_id}>{s.scenario_id} · {percent(s.confidence)}</span>)}</div><h3>Время по этапам</h3>{Object.entries(selected.stages_ms).map(([name, duration]) => <div className="timing-row" key={name}><span>{name}</span><strong>{millis(duration)}</strong></div>)}<details><summary>Полная трассировка</summary><pre>{JSON.stringify(selected, null, 2)}</pre></details></section></div>}
  </div>;
}
function MessageIcon() { return <span className="empty-icon"><Activity size={24} /></span>; }

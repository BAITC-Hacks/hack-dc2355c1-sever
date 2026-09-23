const rows = document.getElementById("rows");
const sessionFilter = document.getElementById("session-filter");
const uncertainFilter = document.getElementById("uncertain-filter");
const refreshBtn = document.getElementById("refresh");
const records = new Map();
let statsData = null, socket = null, statsTimer = null, retryTimer = null, loading = false, loadError = false;
let feedState = "Подключаюсь…";
const uncertain = t => ["clarify","handoff"].includes(t.decision?.action) ||
  (t.decision?.scenarios?.length > 0 && topConf(t.decision) < .75);
function storeTrace(t) {
  records.set(t.session_id+":"+t.turn,t);
  if (records.size > 200) {
    const oldest = Array.from(records.entries()).sort((a,b)=>a[1].ts-b[1].ts)[0];
    records.delete(oldest[0]);
  }
}
function render() {
  const selected = sessionFilter.value;
  const sessions = Array.from(new Set(Array.from(records.values()).sort((a,b)=>b.ts-a.ts).map(t=>t.session_id)));
  sessionFilter.replaceChildren(new Option(tr("Все сессии"),""));
  sessions.forEach(id => sessionFilter.add(new Option(id,id)));
  sessionFilter.value = sessions.includes(selected) ? selected : "";
  const traces = Array.from(records.values()).filter(t => (!sessionFilter.value || t.session_id === sessionFilter.value) &&
    (!uncertainFilter.checked || uncertain(t))).sort((a,b)=>b.ts-a.ts);
  rows.innerHTML = traces.map(t => '<tr class="' + (uncertain(t)?'uncertain':'') + '">' +
    '<td class="mono">'+esc(new Date(t.ts*1000).toLocaleTimeString(I18N.lang === "kk" ? "kk-KZ" : "ru-RU"))+'</td>' +
    '<td class="mono">'+esc(t.session_id)+'<br>#'+esc(t.turn)+'</td><td>'+esc(t.user_text)+'</td>' +
    '<td class="trace-cell">'+traceHtml(t)+'</td><td>'+esc(t.bot_text)+'</td></tr>').join("") ||
    '<tr><td colspan="5" class="table-empty">'+h(records.size ? "По этому фильтру реплик нет" : "Трассировок пока нет")+'</td></tr>';
  document.getElementById("feed-status").textContent = tr(feedState);
  document.getElementById("load-status").textContent = loadError ? tr("Не удалось загрузить данные. Попробуйте обновить.") : loading ? tr("Загрузка…") : "";
  renderStats();
}
function renderStats() {
  if (!statsData) return;
  const s = statsData, pct = value => Math.round((Number(value)||0)*100)+"%";
  const kpis=[
    ["Реплик",s.turns],["Только быстрый путь",pct(s.fast_only_rate)],["Эскалаций",pct(s.escalation_rate)],
    ["Переспросов",pct(s.clarify_rate)],["Передач оператору",pct(s.handoff_rate)],
    ["Роутер p50",duration(s.router_ms_p50)],["Роутер p95",duration(s.router_ms_p95)],
    ["До звука p50",duration(s.end_to_audio_p50)],["Неуверенных",s.low_confidence]
  ];
  document.getElementById("kpis").innerHTML = kpis.map(([label,value])=>
    '<div class="card kpi"><div class="v">'+esc(value ?? "—")+'</div><div class="l">'+h(label)+'</div></div>').join("");
  const counts=Object.entries(s.by_scenario || {}), max=Math.max(1,...counts.map(([,v])=>Number(v)||0));
  document.getElementById("byScenario").innerHTML=counts.map(([key,value])=>
    '<tr><td class="mono">'+esc(key)+'</td><td>'+esc(value)+'</td><td><span class="bar" style="width:'+
    Math.max(0,Math.min(200,Number(value)/max*200))+'px"></span></td></tr>').join("");
}
async function getJson(path) {
  const response=await fetch(path);
  if (!response.ok) throw new Error("HTTP "+response.status);
  return response.json();
}
async function load() {
  if (loading) return;
  loading=true;loadError=false;refreshBtn.disabled=true;render();
  try {
    const [traces,stats]=await Promise.all([getJson("/api/traces?limit=200"),getJson("/api/stats")]);
    traces.forEach(storeTrace);statsData=stats;
  } catch {loadError=true;}
  finally {loading=false;refreshBtn.disabled=false;render();}
}
function connectFeed() {
  socket=new WebSocket(wsUrl("/ws/supervisor"));
  socket.onopen=()=>{feedState="Подключено";render();load();};
  socket.onmessage=event=>{
    try {storeTrace(JSON.parse(event.data));render();} catch {loadError=true;render();}
    clearTimeout(statsTimer);
    statsTimer=setTimeout(async()=>{
      try {statsData=await getJson("/api/stats");renderStats();} catch {loadError=true;render();}
    },500);
  };
  socket.onclose=()=>{
    feedState="Переподключение…";render();
    clearTimeout(retryTimer);retryTimer=setTimeout(connectFeed,2000);
  };
}
sessionFilter.onchange=render;
uncertainFilter.onchange=render;
refreshBtn.onclick=load;
window.addEventListener("uilanguagechange",render);
render();
load();
connectFeed();

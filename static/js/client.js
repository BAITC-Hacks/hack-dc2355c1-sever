const chat = document.getElementById("chat");
const micBtn = document.getElementById("mic");
const input = document.getElementById("text");
const statusEl = document.getElementById("status");

let ws, ttsMode = "browser", audioChunks = [], lastBot = null, recorder = null, speechEndAt = 0;

function add(role, html) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = html;
  chat.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

function connect() {
  ws = new WebSocket(wsUrl("/ws/session"));
  ws.binaryType = "arraybuffer";
  ws.onopen = () => (statusEl.textContent = "Подключено");
  ws.onclose = () => { statusEl.textContent = "Соединение потеряно, переподключаюсь…"; setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") { audioChunks.push(ev.data); return; }
    const m = JSON.parse(ev.data);
    if (m.type === "session") ttsMode = m.tts;
    if (m.type === "transcript") add("user", esc(m.text || "(не расслышал)"));
    if (m.type === "trace") {
      const t = m.trace;
      lastBot = add("bot", `${esc(t.bot_text)}<div class="trace">${traceHtml(t)}</div>`);
      statusEl.textContent = "";
      if (ttsMode === "browser") speak(t.bot_text, t.decision.language);
    }
    if (m.type === "tts_start") audioChunks = [];
    if (m.type === "tts_end") playAudio();
    if (m.type === "timing" && lastBot) lastBot.querySelector(".stages").textContent = stagesText(m.stages_ms);
    if (m.type === "error") statusEl.textContent = "Ошибка: " + m.message;
  };
}

function playAudio() {
  if (!audioChunks.length) return;
  const audio = new Audio(URL.createObjectURL(new Blob(audioChunks, { type: "audio/mpeg" })));
  audio.play().catch(() => {});
}

function speak(text, lang) {
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === "kk" ? "kk-KZ" : "ru-RU";
  speechSynthesis.speak(u);
}

function sendText() {
  const text = input.value.trim();
  if (!text || ws.readyState !== 1) return;
  add("user", esc(text));
  ws.send(JSON.stringify({ type: "text", text }));
  input.value = "";
  statusEl.textContent = "Думаю…";
}

async function toggleMic() {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { statusEl.textContent = "Нет доступа к микрофону — используйте текст"; return; }
  const chunks = [];
  recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    micBtn.classList.remove("rec");
    micBtn.textContent = "🎙 Говорить";
    speechEndAt = performance.now();
    statusEl.textContent = "Распознаю…";
    ws.send(await new Blob(chunks, { type: "audio/webm" }).arrayBuffer());
  };
  recorder.start();
  micBtn.classList.add("rec");
  micBtn.textContent = "■ Готово";
  statusEl.textContent = "Слушаю… нажмите ещё раз, когда закончите";
}

micBtn.onclick = toggleMic;
document.getElementById("send").onclick = sendText;
input.onkeydown = (e) => e.key === "Enter" && sendText();
connect();

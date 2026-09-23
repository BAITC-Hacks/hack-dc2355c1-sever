const chat = document.getElementById("chat");
const micBtn = document.getElementById("mic");
const input = document.getElementById("text");
const statusEl = document.getElementById("status");

let ws, ttsMode = "browser", lastBot = null, partialBot = null, recorder = null;

function add(role, html) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = html;
  chat.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

// Потоковое воспроизведение mp3: звук начинается с первых чанков (MediaSource),
// fallback для браузеров без MediaSource — собрать чанки и сыграть целиком.
const player = {
  audio: null, source: null, buffer: null, queue: [], ended: false, fallback: [],
  start() {
    this.queue = []; this.ended = false; this.fallback = [];
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) { this.source = null; return; }
    this.source = new MediaSource();
    this.audio = new Audio(URL.createObjectURL(this.source));
    this.source.addEventListener("sourceopen", () => {
      this.buffer = this.source.addSourceBuffer("audio/mpeg");
      this.buffer.addEventListener("updateend", () => this.pump());
      this.pump();
    });
    this.audio.play().catch(() => {});
  },
  push(chunk) {
    if (!this.source) { this.fallback.push(chunk); return; }
    this.queue.push(chunk); this.pump();
  },
  end() {
    if (!this.source) {
      if (this.fallback.length) new Audio(URL.createObjectURL(new Blob(this.fallback, { type: "audio/mpeg" }))).play().catch(() => {});
      return;
    }
    this.ended = true; this.pump();
  },
  pump() {
    if (!this.buffer || this.buffer.updating) return;
    if (this.queue.length) { this.buffer.appendBuffer(this.queue.shift()); return; }
    if (this.ended && this.source.readyState === "open") this.source.endOfStream();
  },
};

function speak(text, lang) {
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === "kk" ? "kk-KZ" : "ru-RU";
  speechSynthesis.speak(u);
}

function connect() {
  ws = new WebSocket(wsUrl("/ws/session"));
  ws.binaryType = "arraybuffer";
  ws.onopen = () => (statusEl.textContent = "Подключено");
  ws.onclose = () => { statusEl.textContent = "Соединение потеряно, переподключаюсь…"; setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") { player.push(ev.data); return; }
    const m = JSON.parse(ev.data);
    if (m.type === "session") ttsMode = m.tts;
    if (m.type === "transcript") add("user", esc(m.text || "(не расслышал)"));
    if (m.type === "bot_partial") {
      if (!partialBot) partialBot = add("bot", "");
      partialBot.textContent = (partialBot.textContent + " " + m.text).trim();
      statusEl.textContent = "";
      if (ttsMode === "browser" && m.speak !== false) speak(m.text, /[әіңғүұқөһ]/i.test(m.text) ? "kk" : "ru");
    }
    if (m.type === "trace") {
      const t = m.trace;
      const html = `${esc(t.bot_text)}<div class="trace">${traceHtml(t)}</div>`;
      if (partialBot) { partialBot.innerHTML = html; lastBot = partialBot; partialBot = null; }
      else { lastBot = add("bot", html); }
      statusEl.textContent = "";
    }
    if (m.type === "tts_start") player.start();
    if (m.type === "tts_end") player.end();
    if (m.type === "final" && lastBot) lastBot.querySelector(".trace").innerHTML = traceHtml(m.trace);
    if (m.type === "error") statusEl.textContent = "Ошибка: " + m.message;
  };
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
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    micBtn.classList.remove("rec");
    micBtn.textContent = "🎙 Говорить";
    statusEl.textContent = "Распознаю…";
    ws.send(await new Blob(chunks, { type: recorder.mimeType }).arrayBuffer());
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

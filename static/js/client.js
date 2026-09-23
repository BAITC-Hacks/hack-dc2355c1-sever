const chat = document.getElementById("chat");
const micBtn = document.getElementById("mic");
const input = document.getElementById("text");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const statePanel = document.getElementById("conversation-state");
const stateLabel = document.getElementById("state-label");
const stateHint = document.getElementById("state-hint");
const languageEl = document.getElementById("language");
const playBtn = document.getElementById("play-audio");

const STATES = {
  connecting: ["Подключаюсь…", "Подождите соединения с оператором."],
  ready: ["Расскажите, чем помочь", "Говорите свободно — на русском, казахском или смешивайте оба языка."],
  permission: ["Включаю микрофон…", "Разрешите доступ к микрофону в браузере."],
  listening: ["Слушаю", "Говорите. Когда закончите, нажмите «Готово»."],
  recognizing: ["Распознаю", "Перевожу вашу речь в текст."],
  thinking: ["Думаю", "Готовлю ответ на ваш вопрос."],
  speaking: ["Говорю", "Прослушайте ответ — затем можно продолжить разговор."],
  disconnected: ["Соединение потеряно", "Переподключаюсь. После подключения начнётся новая сессия."],
};
let ws, connected = false, state = "connecting", ttsMode = "browser";
let recorder = null, micStream = null, pending = false, serverDone = true;
let turnBot = null, turnTrace = null, partialText = "", browserSpoken = false;
let audioPlaying = false, speechPending = 0, speechEpoch = 0, reconnectTimer;

function setState(next) {
  state = next;
  statePanel.dataset.state = next;
  [stateLabel.textContent, stateHint.textContent] = STATES[next].map(tr);
  window.voiceOrb?.setState(next);
  document.querySelectorAll("[data-step]").forEach((el) => {
    if (el.dataset.step === next) el.setAttribute("aria-current", "step");
    else el.removeAttribute("aria-current");
  });
  const recording = next === "listening";
  micBtn.classList.toggle("rec", recording);
  micBtn.setAttribute("aria-pressed", String(recording));
  document.getElementById("mic-label").textContent = tr(recording ? "Готово" : "Нажмите и говорите");
  const ready = connected && next === "ready";
  micBtn.disabled = !ready && !recording;
  input.disabled = !ready;
  sendBtn.disabled = !ready || !input.value.trim();
  document.querySelectorAll("[data-example]").forEach(button => { button.disabled = !ready; });
}

function settle() {
  if (!connected || state === "listening" || state === "permission") return;
  if (audioPlaying) setState("speaking");
  else if (speechPending || player.waiting || (pending && !serverDone)) setState("thinking");
  else { pending = false; setState("ready"); }
}

function add(role, text) {
  document.body.classList.add("has-conversation");
  const el = document.createElement("div");
  el.className = "msg " + role;
  const label = document.createElement("span");
  label.className = "message-label";
  label.dataset.i18n = role === "user" ? "Вы" : "Помощник";
  label.textContent = tr(label.dataset.i18n);
  const content = document.createElement("div");
  content.className = "message-text";
  content.textContent = text;
  el.append(label, content);
  document.getElementById("chat-empty").hidden = true;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

const traceHistory = new Map();
let selectedTrace = "", detectedLanguage = "", sessionId = "";
let noticeKey = "", noticeSuffix = "";
const traceContent = document.getElementById("trace-content");
const emptyTraceMarkup = traceContent.innerHTML;
const turnSelect = document.getElementById("trace-turn");

function notice(key, suffix = "") {
  noticeKey = key; noticeSuffix = suffix;
  statusEl.textContent = tr(key) + suffix;
}
function updateLanguage() {
  const name = { ru: "RU · " + tr("Русский"), kk: "KZ · Қазақша", mixed: "RU / KZ · " + tr("Смешанный") }[detectedLanguage];
  languageEl.textContent = name || "RU / KZ";
  languageEl.title = tr("Язык речи");
}
function showInspector() {
  const trace = traceHistory.get(selectedTrace);
  const openDetails = Array.from(traceContent.querySelectorAll("details")).map((el,i) => el.open ? i : -1);
  traceContent.innerHTML = trace ? traceHtml(trace) : emptyTraceMarkup;
  if (trace) traceContent.querySelectorAll("details").forEach((el,i) => { el.open = openDetails.includes(i); });
  else I18N.apply(traceContent);
}
function updateTraceOptions() {
  turnSelect.replaceChildren();
  traceHistory.forEach((trace,key) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = tr("Реплика") + " " + trace.turn + " · " + trace.user_text.slice(0,48);
    turnSelect.appendChild(option);
  });
  turnSelect.value = selectedTrace;
  document.getElementById("trace-selection").hidden = !traceHistory.size;
}
function renderTrace(trace) {
  turnTrace = trace;
  if (!turnBot) turnBot = add("bot", trace.bot_text);
  turnBot.querySelector(".message-text").textContent = trace.bot_text;
  const key = trace.session_id + ":" + trace.turn;
  const fresh = !traceHistory.has(key);
  traceHistory.set(key,trace);
  if (fresh || !selectedTrace) selectedTrace = key;
  if (!turnBot.querySelector(".message-trace-link")) {
    const button = document.createElement("button");
    button.className = "message-trace-link";
    button.type = "button";
    button.dataset.i18n = "Работа агента";
    button.textContent = tr("Работа агента");
    button.onclick = () => {
      selectedTrace = key;
      setInspector(true);
      updateTraceOptions();
      showInspector();
      if (matchMedia("(max-width: 760px)").matches) document.getElementById("inspector").scrollIntoView({block:"start"});
    };
    turnBot.appendChild(button);
  }
  detectedLanguage = trace.decision.language;
  updateLanguage();
  updateTraceOptions();
  if (selectedTrace === key) showInspector();
  chat.scrollTop = chat.scrollHeight;
}

function setInspector(visible) {
  document.getElementById("inspector").hidden = !visible;
  document.querySelector(".workspace").classList.toggle("inspector-hidden", !visible);
  document.getElementById("toggle-inspector").setAttribute("aria-pressed", String(visible));
}
turnSelect.onchange = () => { selectedTrace = turnSelect.value; showInspector(); };
document.getElementById("toggle-inspector").onclick = () => setInspector(document.getElementById("inspector").hidden);

function resetSpeech() {
  speechEpoch++;
  speechPending = 0;
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  audioPlaying = false;
}

function beginTurn() {
  player.dispose();
  resetSpeech();
  pending = true;
  serverDone = false;
  turnBot = null;
  turnTrace = null;
  partialText = "";
  browserSpoken = false;
  notice("");
}

// Сохраняем MediaSource для первых чанков и Blob для браузеров без поддержки mp3-потока.
const player = {
  audio: null, source: null, buffer: null, queue: [], ended: false,
  fallback: [], url: null, waiting: false,
  dispose() {
    if (this.audio) {
      this.audio.onplaying = this.audio.onended = this.audio.onerror = null;
      this.audio.pause();
      this.audio.removeAttribute("src");
      this.audio.load();
    }
    if (this.url) URL.revokeObjectURL(this.url);
    this.audio = this.source = this.buffer = this.url = null;
    this.queue = []; this.fallback = []; this.ended = false; this.waiting = false;
    playBtn.hidden = true;
    audioPlaying = false;
  },
  attach(url) {
    this.url = url;
    const audio = this.audio = new Audio(url);
    audio.onplaying = () => {
      if (this.audio !== audio) return;
      this.waiting = true;
      audioPlaying = true;
      playBtn.hidden = true;
      settle();
    };
    audio.onended = () => {
      if (this.audio !== audio) return;
      this.waiting = false;
      audioPlaying = false;
      playBtn.hidden = true;
      settle();
    };
    audio.onerror = () => { if (this.audio === audio) this.fail(); };
    this.play();
  },
  play() {
    const audio = this.audio;
    if (!audio) return;
    this.waiting = true;
    playBtn.hidden = true;
    audio.play().catch(() => {
      if (this.audio !== audio) return;
      this.waiting = false;
      audioPlaying = false;
      playBtn.hidden = false;
      notice("Браузер не начал озвучку. Нажмите «Воспроизвести ответ» или продолжите текстом.");
      settle();
    });
  },
  start() {
    this.dispose();
    this.waiting = true;
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) return;
    const source = this.source = new MediaSource();
    source.addEventListener("sourceopen", () => {
      if (this.source !== source) return;
      try {
        this.buffer = source.addSourceBuffer("audio/mpeg");
        this.buffer.addEventListener("updateend", () => { if (this.source === source) this.pump(); });
        this.pump();
      } catch { this.fail(); }
    }, { once: true });
    this.attach(URL.createObjectURL(source));
  },
  push(chunk) {
    if (!this.source) { this.fallback.push(chunk); return; }
    this.queue.push(chunk);
    this.pump();
  },
  end() {
    this.ended = true;
    if (!this.source) {
      if (this.fallback.length) this.attach(URL.createObjectURL(new Blob(this.fallback, { type: "audio/mpeg" })));
      else { this.waiting = false; settle(); }
      return;
    }
    this.pump();
  },
  pump() {
    if (!this.buffer || this.buffer.updating || this.source.readyState !== "open") return;
    try {
      if (this.queue.length) { this.buffer.appendBuffer(this.queue.shift()); return; }
      if (this.ended) this.source.endOfStream();
    } catch { this.fail(); }
  },
  fail() {
    this.dispose();
    notice("Не удалось воспроизвести звук. Ответ доступен в ленте.");
    settle();
  },
};

function speak(text, lang) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    notice("Озвучка недоступна в этом браузере. Ответ доступен в ленте.");
    return;
  }
  const epoch = speechEpoch;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang === "kk" ? "kk-KZ" : "ru-RU";
  speechPending++;
  utterance.onstart = () => { if (epoch === speechEpoch) { audioPlaying = true; settle(); } };
  const finish = () => {
    if (epoch !== speechEpoch) return;
    speechPending = Math.max(0, speechPending - 1);
    audioPlaying = false;
    settle();
  };
  utterance.onend = finish;
  utterance.onerror = () => {
    if (epoch !== speechEpoch) return;
    notice("Озвучка недоступна. Ответ доступен в ленте.");
    finish();
  };
  window.speechSynthesis.speak(utterance);
}

function connect() {
  const socket = ws = new WebSocket(wsUrl("/ws/session"));
  socket.binaryType = "arraybuffer";
  socket.onclose = () => {
    if (ws !== socket) return;
    connected = false;
    pending = false;
    player.dispose();
    resetSpeech();
    if (recorder && recorder.state === "recording") recorder.stop();
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    window.voiceOrb?.detachStream();
    setState("disconnected");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1000);
  };
  socket.onerror = () => { notice("Не удалось связаться с сервером."); };
  socket.onmessage = (event) => {
    if (ws !== socket) return;
    if (typeof event.data !== "string") { player.push(event.data); return; }
    let m;
    try { m = JSON.parse(event.data); }
    catch { notice("Не удалось прочитать сообщение сервера."); return; }
    if (m.type === "session") {
      connected = true;
      ttsMode = m.tts;
      detectedLanguage = "";
      updateLanguage();
      sessionId = m.session_id;
      document.getElementById("session-label").removeAttribute("data-i18n");
      document.getElementById("session-label").textContent = tr("Сессия") + " · " + sessionId;
      notice("Соединение установлено.");
      setState("ready");
    }
    if (m.type === "transcript") {
      if (m.text && m.text.trim()) { add("user", m.text); setState("thinking"); }
      else {
        serverDone = true;
        notice("Не расслышал. Попробуйте ещё раз или напишите сообщение.");
        settle();
      }
    }
    if (m.type === "bot_partial" && m.text) {
      // После trace системный ответ уже показан и озвучен целиком.
      if (!turnTrace) {
        partialText = (partialText + " " + m.text).trim();
        if (!turnBot) turnBot = add("bot", "");
        turnBot.querySelector(".message-text").textContent = partialText;
        if (ttsMode === "browser") {
          browserSpoken = true;
          speak(m.text, /[әіңғүұқөһ]/i.test(m.text) ? "kk" : "ru");
        }
      }
    }
    if (m.type === "trace" || m.type === "final") {
      renderTrace(m.trace);
      if (ttsMode === "browser" && !browserSpoken) {
        browserSpoken = true;
        speak(m.trace.bot_text, m.trace.decision.reply_language);
      }
      if (m.type === "final") { serverDone = true; settle(); }
    }
    if (m.type === "tts_start") player.start();
    if (m.type === "tts_end") player.end();
    if (m.type === "error") {
      if (String(m.message).startsWith("TTS:")) {
        player.dispose();
        notice("Не удалось воспроизвести звук. Ответ доступен в ленте.");
      } else {
        // Сервер при ошибке хода не присылает final — освобождаем ввод сами.
        notice(state === "recognizing"
          ? "Не удалось распознать речь. Попробуйте ещё раз или напишите сообщение."
          : "Не удалось получить ответ. Попробуйте позже.");
        serverDone = true;
        player.dispose();
        resetSpeech();
      }
      settle();
    }
  };
}

function sendText() {
  const text = input.value.trim();
  if (!text || !connected || state !== "ready" || ws.readyState !== WebSocket.OPEN) return;
  beginTurn();
  add("user", text);
  ws.send(JSON.stringify({ type: "text", text }));
  input.value = "";
  setState("thinking");
}

async function toggleMic() {
  if (recorder && recorder.state === "recording") {
    setState("recognizing");
    recorder.stop();
    window.voiceOrb?.detachStream();
    return;
  }
  if (!connected || state !== "ready") return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    notice("Микрофон недоступен. Откройте сайт по HTTPS или localhost, либо используйте текст.");
    return;
  }
  const socket = ws;
  setState("permission");
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!connected || ws !== socket || state !== "permission") {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    micStream = stream;
    const current = recorder = new MediaRecorder(stream);
    const chunks = [];
    let failed = false;
    current.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    current.onerror = () => {
      failed = true;
      window.voiceOrb?.detachStream();
      stream.getTracks().forEach((track) => track.stop());
      notice("Ошибка записи. Попробуйте ещё раз или используйте текст.");
      serverDone = true;
      setState(connected ? "ready" : "disconnected");
    };
    current.onstop = async () => {
      window.voiceOrb?.detachStream();
      stream.getTracks().forEach((track) => track.stop());
      if (recorder === current) recorder = null;
      if (micStream === stream) micStream = null;
      if (failed || !connected || ws !== socket) return;
      try {
        const audio = await new Blob(chunks, { type: current.mimeType }).arrayBuffer();
        if (!connected || ws !== socket) return;
        if (!audio.byteLength) throw new Error("empty");
        setState("recognizing");
        socket.send(audio);
      } catch {
        serverDone = true;
        notice("Не удалось отправить запись. Попробуйте ещё раз.");
        settle();
      }
    };
    beginTurn();
    current.start();
    window.voiceOrb?.attachStream(stream);
    setState("listening");
  } catch {
    window.voiceOrb?.detachStream();
    if (stream) stream.getTracks().forEach((track) => track.stop());
    recorder = micStream = null;
    pending = false;
    notice("Не удалось включить микрофон. Проверьте разрешение браузера или используйте текст.");
    setState(connected ? "ready" : "disconnected");
  }
}

micBtn.onclick = toggleMic;
sendBtn.onclick = sendText;
playBtn.onclick = () => { player.play(); settle(); };
input.oninput = () => { sendBtn.disabled = state !== "ready" || !input.value.trim(); };
input.onkeydown = (event) => {
  if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); sendText(); }
};
document.querySelectorAll("[data-example]").forEach(button => {
  button.onclick = () => {
    if (state !== "ready") return;
    const examples = I18N.lang === "kk"
      ? {auto:"Көлігімді сақтандырғым келеді",payment:"Төлемімнің өткенін тексеріңізші",claim:"Сақтандыру жағдайы туралы хабарлағым келеді"}
      : {auto:"Хочу застраховать автомобиль",payment:"Проверьте, пожалуйста, прошёл ли мой платёж",claim:"Хочу сообщить о страховом случае"};
    input.value = examples[button.dataset.example];
    input.dispatchEvent(new Event("input"));
    input.focus();
  };
});
window.addEventListener("uilanguagechange", () => {
  setState(state);
  updateLanguage();
  notice(noticeKey, noticeSuffix);
  updateTraceOptions();
  showInspector();
  if (sessionId) document.getElementById("session-label").textContent = tr("Сессия") + " · " + sessionId;
});
setState("connecting");
connect();

import { useEffect, useRef, useState } from "react";
import { AudioPlayer } from "@/lib/audio-player";

export interface ScenarioHit { scenario_id: string; confidence: number; reason?: string }
export interface TraceAction { name: string; mode?: "preview" | "execute"; args?: Record<string, unknown>; result?: unknown; guard?: string; blocked?: boolean }
export interface Trace {
  session_id: string; turn: number; user_text: string; bot_text: string; ts: number;
  path: string; stages_ms: Record<string, number>; handoff_queue?: string | null;
  actions?: TraceAction[]; client_id?: string | null; active_scenario?: string | null; topic_queue?: string[];
  decision: {
    action: string; language: string; reply_language: string; reasoning: string; policy_note?: string;
    scenarios: ScenarioHit[]; alternatives?: ScenarioHit[]; slots: Record<string, unknown>;
  };
}
export interface Message { id: string; role: "user" | "assistant"; text: string; trace?: Trace }
export const wsUrl = (path: string) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

export function useConversation() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [requestingMic, setRequestingMic] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [generation, setGeneration] = useState(0);
  const socket = useRef<WebSocket | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const activeStream = useRef<MediaStream | null>(null);
  const player = useRef(new AudioPlayer());
  const muteRef = useRef(false);
  const pending = useRef(false);
  const micPending = useRef(false);
  const recordingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const turnTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const stopRecording = (discard = false) => {
    clearTimeout(recordingTimer.current);
    if (recorder.current && recorder.current.state !== "inactive") {
      if (discard) recorder.current.onstop = null;
      recorder.current.stop();
    }
    activeStream.current?.getTracks().forEach(track => track.stop());
    activeStream.current = null;
    recorder.current = null;
    setStream(null); setRecording(false);
  };
  const stopPlayback = () => { player.current.stop(); window.speechSynthesis?.cancel(); };
  const endTurn = () => { clearTimeout(turnTimer.current); pending.current = false; setBusy(false); };
  const beginTurn = () => {
    pending.current = true; setBusy(true); setError("");
    clearTimeout(turnTimer.current);
    turnTimer.current = setTimeout(() => {
      setError("Ответ занимает слишком много времени. Соединение будет восстановлено — попробуйте ещё раз.");
      socket.current?.close();
    }, 120_000);
  };

  useEffect(() => {
    let disposed = false;
    let retry: ReturnType<typeof setTimeout>;
    let partialId: string | null = null;
    let ttsMode = "browser";
    let hasConnected = false;
    player.current.onBlocked = () => setError("Браузер не воспроизвёл звук. Ответ доступен в переписке.");
    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(wsUrl("/ws/session"));
      socket.current = ws;
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        if (disposed) return;
        setConnected(true);
        if (hasConnected) {
          setMessages([]);
          setError("Соединение восстановлено. Начат новый диалог: расскажите, чем помочь.");
        }
        hasConnected = true;
      };
      ws.onclose = () => {
        if (disposed) return;
        setConnected(false); endTurn(); stopRecording(true); stopPlayback(); partialId = null;
        retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => { if (!disposed) setError("Не удалось подключиться к серверу. Повторяем подключение…"); };
      ws.onmessage = event => {
        if (disposed) return;
        if (typeof event.data !== "string") { player.current.push(event.data); return; }
        let m;
        try { m = JSON.parse(event.data); } catch { return; }
        if (m.type === "session") { setSessionId(m.session_id); ttsMode = m.tts; }
        if (m.type === "transcript") {
          if (!m.text?.trim()) { endTurn(); setError("Не удалось расслышать. Повторите или напишите текстом."); return; }
          setMessages(items => [...items, { id: crypto.randomUUID(), role: "user", text: m.text }]);
        }
        if (m.type === "bot_partial") {
          const id = partialId ?? crypto.randomUUID();
          partialId = id;
          setMessages(items => items.some(item => item.id === id)
            ? items.map(item => item.id === id ? { ...item, text: `${item.text} ${m.text}`.trim() } : item)
            : [...items, { id, role: "assistant", text: m.text }]);
          if (ttsMode === "browser" && m.speak !== false && !muteRef.current && "speechSynthesis" in window) {
            const speech = new SpeechSynthesisUtterance(m.text);
            speech.lang = /[әіңғүұқөһ]/i.test(m.text) ? "kk-KZ" : "ru-RU";
            window.speechSynthesis.speak(speech);
          }
        }
        if (m.type === "trace" || m.type === "final") {
          const trace = m.trace as Trace;
          const id = partialId ?? `turn-${trace.turn}`;
          partialId = id;
          setMessages(items => items.some(item => item.id === id)
            ? items.map(item => item.id === id ? { ...item, text: trace.bot_text, trace } : item)
            : [...items, { id, role: "assistant", text: trace.bot_text, trace }]);
          if (m.type === "final") { partialId = null; endTurn(); }
        }
        if (m.type === "tts_start") player.current.start();
        if (m.type === "tts_end") player.current.end();
        if (m.type === "error") {
          setError(m.message);
          // TTS errors still have a final response on the way.
          if (!String(m.message).startsWith("TTS:")) { partialId = null; endTurn(); }
        }
      };
    };
    connect();
    return () => {
      disposed = true; clearTimeout(retry); clearTimeout(turnTimer.current);
      stopRecording(true); stopPlayback();
      socket.current?.close(); socket.current = null;
    };
  }, [generation]);

  const send = (text: string) => {
    const value = text.trim();
    if (!value || pending.current || micPending.current || recorder.current || socket.current?.readyState !== WebSocket.OPEN) return false;
    stopPlayback(); beginTurn();
    setMessages(items => [...items, { id: crypto.randomUUID(), role: "user", text: value }]);
    socket.current.send(JSON.stringify({ type: "text", text: value }));
    return true;
  };

  const toggleMic = async () => {
    if (recorder.current?.state === "recording") { stopRecording(); return; }
    if (pending.current || micPending.current || socket.current?.readyState !== WebSocket.OPEN) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Запись недоступна. Используйте HTTPS или localhost либо напишите текстом."); return;
    }
    const ws = socket.current;
    micPending.current = true; setRequestingMic(true); setError(""); stopPlayback();
    let media: MediaStream | null = null;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (socket.current !== ws || ws.readyState !== WebSocket.OPEN) { media.getTracks().forEach(track => track.stop()); return; }
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(type => MediaRecorder.isTypeSupported(type));
      const rec = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      rec.onerror = () => { stopRecording(true); setError("Не удалось записать аудио. Попробуйте ещё раз или напишите текстом."); };
      rec.onstop = async () => {
        if (socket.current !== ws || ws.readyState !== WebSocket.OPEN) return;
        if (!chunks.length) { setError("Запись пуста. Попробуйте говорить чуть дольше."); return; }
        beginTurn();
        const bytes = await new Blob(chunks, { type: rec.mimeType }).arrayBuffer();
        if (socket.current === ws && ws.readyState === WebSocket.OPEN) ws.send(bytes);
        else endTurn();
      };
      activeStream.current = media; recorder.current = rec;
      rec.start(250); setStream(media); setRecording(true);
      recordingTimer.current = setTimeout(() => stopRecording(), 60_000);
    } catch {
      media?.getTracks().forEach(track => track.stop());
      setError("Нет доступа к микрофону. Разрешите его в настройках браузера или напишите текстом.");
    } finally { micPending.current = false; setRequestingMic(false); }
  };
  const toggleMute = () => {
    muteRef.current = !muteRef.current; setMuted(muteRef.current); player.current.setMuted(muteRef.current);
    if (muteRef.current) window.speechSynthesis?.cancel();
  };
  const reset = () => {
    stopRecording(true); stopPlayback(); endTurn(); setMessages([]); setError(""); setConnected(false); setSessionId("");
    setGeneration(value => value + 1);
  };
  return { messages, connected, busy, recording, requestingMic, stream, error, muted, sessionId, send, toggleMic, toggleMute, reset, clearError: () => setError("") };
}

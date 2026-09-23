import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUp, ArrowUpRight, AudioLines, Check, ChevronRight, CircleHelp, Globe2, LayoutDashboard, Loader2, MessageSquare, Mic, Plus, Radio, Sparkles, Square, Volume2, VolumeX, X } from "lucide-react";
import { VoicePoweredOrb } from "@/components/ui/voice-powered-orb";
import { Button } from "@/components/ui/button";
import { useConversation } from "./hooks/use-conversation";

export function Header({ supervisor = false }: { supervisor?: boolean }) {
  return <header className="site-header">
    <a className="brand" href="/" aria-label="Voice Router — главная"><span className="brand-icon"><AudioLines size={22} /></span><span>voice<span className="brand-light">router</span><span className="brand-dot">.</span></span></a>
    <nav aria-label="Основная навигация"><a className={!supervisor ? "nav-active" : ""} href="/"><MessageSquare size={15} /> Ассистент</a><a className={supervisor ? "nav-active" : ""} href="/supervisor"><LayoutDashboard size={15} /> Супервизор <ArrowUpRight size={13} /></a></nav>
    <div className="header-note"><span className="tiny-orbit" /> Голос становится действием</div>
  </header>;
}

const suggestions = [
  { icon: CircleHelp, label: "Узнать баланс", text: "Как узнать мой баланс?" },
  { icon: Sparkles, label: "Подобрать тариф", text: "Помогите подобрать тариф" },
  { icon: Globe2, label: "Қазақша сөйлесейік", text: "Сәлеметсіз бе! Қазақша сөйлесейік." },
];

export function App() {
  const c = useConversation();
  const [draft, setDraft] = useState("");
  const [voiceDetected, setVoiceDetected] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const hasMessages = c.messages.length > 0;
  const disabled = !c.connected || c.busy || c.recording || c.requestingMic;
  const status = c.requestingMic ? "Разрешите доступ к микрофону" : c.recording ? voiceDetected ? "Слышу вас" : "Слушаю вас" : c.busy ? "Готовлю ответ" : "Готов к разговору";
  useEffect(() => { if (hasMessages) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [c.messages, c.busy, hasMessages]);
  useEffect(() => {
    if (textarea.current) { textarea.current.style.height = "auto"; textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 160)}px`; }
  }, [draft]);
  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (c.send(draft)) { setDraft(""); textarea.current?.focus(); }
  };

  return <div className="app-shell">
    <Header />
    <main className={`assistant-main ${hasMessages ? "has-messages" : ""}`}>
      <div className="session-bar"><span className="section-label"><span className="small-dot" /> ПЕРСОНАЛЬНЫЙ АССИСТЕНТ</span><Button variant="ghost" size="sm" onClick={() => { c.reset(); setDraft(""); }} disabled={c.requestingMic} className="new-chat"><Plus size={15} /> Новый диалог</Button></div>
      <section className="hero" aria-label="Голосовой ассистент">
        <div className="hero-heading"><div className="eyebrow">МЕНЬШЕ КЛИКОВ. БОЛЬШЕ ОБЩЕНИЯ.</div><h1>Просто начните <span>разговор.</span></h1><p>Расскажите, чем помочь. Голосом или текстом — как вам удобнее.</p></div>
        <div className={`orb-stage ${c.recording ? "is-listening" : ""}`}>
          <div className="orb-ambient" />
          <VoicePoweredOrb enableVoiceControl={c.recording} audioStream={c.stream} onVoiceDetected={setVoiceDetected} className="orb-canvas" />
          <div className="orb-center"><AudioLines size={hasMessages ? 19 : 28} strokeWidth={1.3} /></div>
        </div>
        <div className="voice-status" role="status">{c.busy || c.requestingMic ? <Loader2 size={13} className="spin" /> : <span className={`status-dot ${c.recording ? "active" : ""}`} />} {status}</div>
        <Button className="talk-button" variant={c.recording ? "destructive" : "default"} size="lg" onClick={() => void c.toggleMic()} disabled={!c.connected || c.busy || c.requestingMic}>
          {c.recording ? <Square size={15} fill="currentColor" /> : <Mic size={18} />}{c.recording ? "Завершить и отправить" : "Начать разговор"}
        </Button>
        <p className="voice-hint">{c.recording ? "Нажмите ещё раз, когда закончите · до 60 секунд" : "Нажмите и говорите. Я слушаю."}</p>
      </section>

      {hasMessages && <section className="conversation" role="log" aria-label="Переписка с ассистентом" aria-live="polite" aria-relevant="additions text">
        {c.messages.map(message => <article key={message.id} className={`message message-${message.role}`}>
          <div className="message-meta">{message.role === "assistant" ? <><span className="message-avatar"><AudioLines size={13} /></span> Voice Router</> : <>Вы <span className="user-avatar">В</span></>}</div>
          <div className="message-content">{message.text}</div>
          {message.trace?.handoff_queue && <div className="handoff-note"><Check size={13} /> Обращение передано оператору</div>}
        </article>)}
        {c.busy && <div className="thinking"><span /><span /><span /><span className="sr-only">Ассистент готовит ответ</span></div>}
        <div ref={end} />
      </section>}

      <div className="composer-area">
        {!hasMessages && <div className="suggestions">{suggestions.map(({ icon: Icon, label, text }) => <button key={label} disabled={disabled} onClick={() => c.send(text)}><Icon size={15} />{label}<ChevronRight size={13} /></button>)}</div>}
        {c.error && <div className="error-notice" role="alert"><span>{c.error}</span><button aria-label="Закрыть уведомление" onClick={c.clearError}><X size={16} /></button></div>}
        <form className={`composer ${c.recording ? "composer-recording" : ""}`} onSubmit={submit}>
          <label className="sr-only" htmlFor="message">Ваше сообщение</label>
          <textarea ref={textarea} id="message" value={draft} onChange={event => setDraft(event.target.value)} placeholder={c.recording ? "Слушаю вас… Текст можно отправить после записи" : "Или напишите, что вас интересует…"} rows={1} maxLength={10000} disabled={c.recording || c.requestingMic} onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
          }} />
          <div className="composer-toolbar"><div className="composer-tools"><Globe2 size={16} /><span>Русский / Қазақша</span><span className="tool-divider" /><button type="button" onClick={c.toggleMute} aria-label={c.muted ? "Включить озвучку ответов" : "Выключить озвучку ответов"} aria-pressed={c.muted} title={c.muted ? "Включить звук" : "Выключить звук"}>{c.muted ? <VolumeX size={17} /> : <Volume2 size={17} />}</button></div>
          <div className="send-tools"><span className="enter-hint">Enter ↵</span><Button type="button" variant="ghost" size="icon" className={`composer-mic ${c.recording ? "recording" : ""}`} aria-label={c.recording ? "Завершить запись" : "Записать голосовое сообщение"} onClick={() => void c.toggleMic()} disabled={!c.connected || c.busy || c.requestingMic}>{c.recording ? <Square size={15} fill="currentColor" /> : <Mic size={18} />}</Button><Button type="submit" size="icon" className="send-button" aria-label="Отправить сообщение" disabled={disabled || !draft.trim()}>{c.busy ? <Loader2 size={18} className="spin" /> : <ArrowUp size={20} />}</Button></div></div>
        </form>
        <p className="composer-caption">Один диалог — два способа общения.<span> Shift + Enter — новая строка</span></p>
      </div>
    </main>
    <footer className="site-footer"><span className="footer-connection"><span className={`connection-dot ${c.connected ? "online" : ""}`} />{c.connected ? "На связи" : "Подключаемся…"}{c.sessionId && <span className="session-id"> / {c.sessionId.slice(0, 8)}</span>}</span><span><Radio size={12} /> Сделано, чтобы слышать вас</span><span>VOICE ROUTER <span className="footer-version">/ 01</span></span></footer>
  </div>;
}

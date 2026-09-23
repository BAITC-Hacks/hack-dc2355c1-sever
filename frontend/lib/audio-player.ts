/** MP3 streaming with a buffered fallback for browsers without MPEG MediaSource. */
export class AudioPlayer {
  private audio: HTMLAudioElement | null = null;
  private source: MediaSource | null = null;
  private buffer: SourceBuffer | null = null;
  private chunks: ArrayBuffer[] = [];
  private complete = false;
  private url: string | null = null;
  private muted = false;
  onBlocked?: () => void;

  setMuted(muted: boolean) { this.muted = muted; if (this.audio) this.audio.muted = muted; }
  start() {
    this.stop();
    this.complete = false;
    if (typeof MediaSource === "undefined" || !MediaSource.isTypeSupported("audio/mpeg")) return;
    const source = new MediaSource();
    this.source = source;
    this.url = URL.createObjectURL(source);
    this.audio = new Audio(this.url);
    this.audio.muted = this.muted;
    source.addEventListener("sourceopen", () => {
      if (this.source !== source) return;
      this.buffer = source.addSourceBuffer("audio/mpeg");
      this.buffer.addEventListener("updateend", () => this.pump());
      this.pump();
    }, { once: true });
    this.play();
  }
  private play() {
    void this.audio?.play().catch(() => { if (!this.muted) this.onBlocked?.(); });
  }
  push(chunk: ArrayBuffer) { this.chunks.push(chunk); if (this.source) this.pump(); }
  end() {
    this.complete = true;
    if (this.source) { this.pump(); return; }
    if (!this.chunks.length) return;
    this.url = URL.createObjectURL(new Blob(this.chunks, { type: "audio/mpeg" }));
    this.chunks = [];
    this.audio = new Audio(this.url);
    this.audio.muted = this.muted;
    this.audio.addEventListener("ended", () => this.stop(), { once: true });
    this.play();
  }
  private pump() {
    if (!this.buffer || this.buffer.updating || this.source?.readyState !== "open") return;
    try {
      const chunk = this.chunks.shift();
      if (chunk) this.buffer.appendBuffer(chunk);
      else if (this.complete) this.source.endOfStream();
    } catch { this.stop(); this.onBlocked?.(); }
  }
  stop() {
    this.audio?.pause();
    if (this.audio) { this.audio.removeAttribute("src"); this.audio.load(); }
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null; this.audio = null; this.source = null; this.buffer = null; this.chunks = [];
  }
}

// Voice playback + amplitude analysis.
//
// Two speech paths mirror the backend TTS providers:
//   - playAudioB64:  ElevenLabs MP3 (server_audio). Routed through a WebAudio
//                    AnalyserNode so the presence can react to the real voice.
//   - speakBrowser:  SpeechSynthesis fallback. No amplitude; the presence uses a
//                    gentle synthetic pulse while speaking instead.
//
// The AudioBus exposes a single smoothed amplitude (0..1) that the visual layer
// samples on its own requestAnimationFrame loop — no React re-renders involved.

export interface SpeechCallbacks {
  onStart?: () => void;
  onEnd?: () => void;
}

class AudioBus {
  /** Smoothed voice amplitude, 0..1. Sampled by the presence each frame. */
  amplitude = 0;
  /** True while server audio is actively playing. */
  speaking = false;

  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private data: Uint8Array<ArrayBuffer> | null = null;
  private raf = 0;
  private attached = new WeakSet<HTMLAudioElement>();

  private ensureCtx(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.ctx) {
      const Ctor = window.AudioContext || (window as any).webkitAudioContext;
      if (!Ctor) return null;
      this.ctx = new Ctor();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;
      this.data = new Uint8Array(new ArrayBuffer(this.analyser.frequencyBinCount));
      this.analyser.connect(this.ctx.destination);
    }
    return this.ctx;
  }

  /** Call from a user gesture so the browser lets audio play. */
  resume(): void {
    const ctx = this.ensureCtx();
    if (ctx && ctx.state === "suspended") void ctx.resume();
  }

  /** Route an <audio> element through the analyser (once per element). */
  attach(el: HTMLAudioElement): void {
    const ctx = this.ensureCtx();
    if (!ctx || !this.analyser || this.attached.has(el)) return;
    try {
      const source = ctx.createMediaElementSource(el);
      source.connect(this.analyser);
      this.attached.add(el);
    } catch {
      /* element already bound to another graph — ignore */
    }
  }

  start(): void {
    this.speaking = true;
    if (this.raf) return;
    const tick = () => {
      if (this.analyser && this.data) {
        this.analyser.getByteTimeDomainData(this.data);
        // RMS around the 128 midpoint → 0..1
        let sum = 0;
        for (let i = 0; i < this.data.length; i++) {
          const v = (this.data[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / this.data.length);
        const target = Math.min(1, rms * 2.2);
        this.amplitude += (target - this.amplitude) * 0.25;
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop(): void {
    this.speaking = false;
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
    this.amplitude = 0;
  }
}

export const audioBus = new AudioBus();

/** Speak text with the browser's built-in SpeechSynthesis (BrowserTTS path). */
export function speakBrowser(text: string, cb: SpeechCallbacks = {}): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    cb.onStart?.();
    cb.onEnd?.();
    return;
  }
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.0;
  utter.pitch = 0.9;
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find((v) => /en-GB|Daniel|Google UK English Male/i.test(v.name));
  if (preferred) utter.voice = preferred;
  utter.onstart = () => {
    audioBus.speaking = true; // synthetic pulse; no real amplitude
    cb.onStart?.();
  };
  utter.onend = () => {
    audioBus.speaking = false;
    cb.onEnd?.();
  };
  window.speechSynthesis.speak(utter);
}

/** Play base64-encoded audio (server_audio path, e.g. ElevenLabs MP3). */
export function playAudioB64(
  audioB64: string,
  mime: string,
  cb: SpeechCallbacks = {},
): void {
  try {
    const bytes = Uint8Array.from(atob(audioB64), (c) => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: mime });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.crossOrigin = "anonymous";
    audioBus.attach(audio);
    audio.onplay = () => {
      audioBus.start();
      cb.onStart?.();
    };
    const finish = () => {
      audioBus.stop();
      cb.onEnd?.();
      URL.revokeObjectURL(url);
    };
    audio.onended = finish;
    audio.onerror = finish;
    void audio.play();
  } catch {
    cb.onStart?.();
    cb.onEnd?.();
  }
}

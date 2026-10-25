// Gapless playback of streamed PCM speech.
//
// Playing each network chunk as its own AudioBufferSourceNode leaves tiny
// timing seams between buffers, heard as rhythmic clicks ("beeps") behind the
// voice. Instead, one AudioWorklet pulls samples from a queue and outputs a
// single continuous signal: there are no buffer boundaries to click. If the
// network stalls, it fades out over a few milliseconds, waits for a bigger
// cushion, and fades back in, so even a stall doesn't pop.

const WORKLET = `
const FADE = 96; // samples (~4 ms at 24 kHz)
class EdenPcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.q = []; this.off = 0; this.buffered = 0;
    this.ended = true; this.playing = false; this.prime = 0; this.gain = 0;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "start") { this.ended = false; if (!this.playing) this.prime = m.prime; }
      else if (m.type === "chunk") { this.q.push(m.samples); this.buffered += m.samples.length; }
      else if (m.type === "end") { this.ended = true; }
      else if (m.type === "reset") { this.q = []; this.off = 0; this.buffered = 0; this.playing = false; this.ended = true; }
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    out.fill(0);
    if (!this.playing) {
      if (this.buffered === 0) return true;
      if (this.buffered < this.prime && !this.ended) return true;
      this.playing = true; this.gain = 0;
    }
    let i = 0;
    while (i < out.length && this.q.length) {
      const head = this.q[0];
      const n = Math.min(out.length - i, head.length - this.off);
      for (let k = 0; k < n; k++) {
        if (this.gain < 1) this.gain = Math.min(1, this.gain + 1 / FADE);
        out[i + k] = head[this.off + k] * this.gain;
      }
      i += n; this.off += n; this.buffered -= n;
      if (this.off >= head.length) { this.q.shift(); this.off = 0; }
    }
    if (i < out.length) {
      // Out of samples: fade the tail we did write so the cut doesn't pop.
      const f = Math.min(i, FADE);
      for (let k = 0; k < f; k++) out[i - f + k] *= 1 - (k + 1) / f;
      this.playing = false;
      if (this.ended) this.port.postMessage({ type: "drained" });
      else { this.prime = Math.min(Math.max(this.prime, 2400) * 2.5, 36000); this.port.postMessage({ type: "underrun" }); }
    }
    return true;
  }
}
registerProcessor("eden-pcm-player", EdenPcmPlayer);
`;

/** Linear resampler that stays continuous across chunk boundaries. */
class Resampler {
  private prev = 0;
  private pos = 1;
  constructor(private readonly step: number) {}

  process(input: Float32Array): Float32Array {
    if (this.step === 1) return input;
    const len = input.length + 1; // virtual buffer: [prev, ...input]
    const at = (j: number) => (j === 0 ? this.prev : input[j - 1]);
    const out: number[] = [];
    let t = this.pos;
    while (t < len - 1) {
      const j = Math.floor(t);
      const frac = t - j;
      out.push(at(j) + frac * (at(j + 1) - at(j)));
      t += this.step;
    }
    this.pos = t - (len - 1);
    this.prev = input[input.length - 1];
    return Float32Array.from(out);
  }
}

export function decodePcm16(b64: string): Float32Array {
  const bin = atob(b64);
  const n = bin.length >> 1;
  const samples = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const v = (bin.charCodeAt(2 * i + 1) << 8) | bin.charCodeAt(2 * i);
    samples[i] = (v >= 0x8000 ? v - 0x10000 : v) / 0x8000;
  }
  return samples;
}

export class PcmStreamPlayer {
  private node: AudioWorkletNode | null = null;
  private ready: Promise<boolean> | null = null;
  private pending: Array<() => void> = [];
  private resampler: Resampler | null = null;
  private onDrained: (() => void) | null = null;

  constructor(private readonly ctx: AudioContext, private readonly output: AudioNode) {}

  /** True once the worklet is loaded; false if this browser can't run it. */
  init(): Promise<boolean> {
    if (this.ready) return this.ready;
    this.ready = (async () => {
      if (!this.ctx.audioWorklet) return false;
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      try {
        await this.ctx.audioWorklet.addModule(url);
        this.node = new AudioWorkletNode(this.ctx, "eden-pcm-player", { outputChannelCount: [1] });
        this.node.connect(this.output);
        this.node.port.onmessage = (e) => {
          if (e.data?.type === "drained") {
            const done = this.onDrained;
            this.onDrained = null;
            done?.();
          }
        };
        this.pending.forEach((f) => f());
        this.pending = [];
        return true;
      } catch {
        return false;
      } finally {
        URL.revokeObjectURL(url);
      }
    })();
    return this.ready;
  }

  private send(f: () => void): void {
    if (this.node) f();
    else this.pending.push(f);
  }

  /** Begin a line. ``onDrained`` fires when every queued sample has played. */
  start(sampleRate: number, onDrained: () => void): void {
    this.onDrained = onDrained;
    this.resampler = new Resampler(sampleRate / this.ctx.sampleRate);
    // ~0.15 s of cushion before the first sound absorbs network jitter.
    const prime = Math.round(this.ctx.sampleRate * 0.15);
    this.send(() => this.node!.port.postMessage({ type: "start", prime }));
  }

  push(pcmB64: string): void {
    const samples = (this.resampler ?? new Resampler(1)).process(decodePcm16(pcmB64));
    if (!samples.length) return;
    this.send(() => this.node!.port.postMessage({ type: "chunk", samples }, [samples.buffer]));
  }

  end(): void {
    this.send(() => this.node!.port.postMessage({ type: "end" }));
  }
}

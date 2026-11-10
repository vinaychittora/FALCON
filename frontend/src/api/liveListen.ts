/** Listening to the sensor live: FALCON passes the decoded sound through, nothing is stored. */

export const LISTEN_URL = "/api/live/audio.pcm";
export const SAMPLE_RATE = 48000;
const LISTEN_STORAGE_KEY = "falcon.listen-volume.v1";
/** Sound buffered before playback starts, so small network gaps do not click. */
const LEAD_SECONDS = 0.35;

export function readListenVolume(): number {
  try {
    const value = Number(localStorage.getItem(LISTEN_STORAGE_KEY));
    return Number.isFinite(value) && value > 0 && value <= 1 ? value : 0.8;
  } catch {
    return 0.8;
  }
}

export function saveListenVolume(value: number): void {
  try {
    localStorage.setItem(LISTEN_STORAGE_KEY, String(value));
  } catch {
    /* per-browser convenience only */
  }
}

/** Signed 16-bit little-endian PCM to floats; an odd trailing byte is kept for later. */
export function pcmToFloat(
  bytes: Uint8Array,
  carry: Uint8Array | null,
): { samples: Float32Array<ArrayBuffer>; rest: Uint8Array | null } {
  const joined = carry?.length
    ? new Uint8Array(carry.length + bytes.length)
    : bytes;
  if (carry?.length) {
    joined.set(carry);
    joined.set(bytes, carry.length);
  }
  const usable = joined.length - (joined.length % 2);
  const view = new DataView(joined.buffer, joined.byteOffset, usable);
  const samples = new Float32Array(usable / 2);
  for (let i = 0; i < samples.length; i += 1)
    samples[i] = view.getInt16(i * 2, true) / 32768;
  return {
    samples,
    rest: usable < joined.length ? joined.slice(usable) : null,
  };
}

/** Level in dBFS (RMS) and peak in dBFS of a block of samples; −Infinity for silence. */
export function level(samples: Float32Array): { rms: number; peak: number } {
  let sum = 0;
  let peak = 0;
  for (const value of samples) {
    sum += value * value;
    peak = Math.max(peak, Math.abs(value));
  }
  const rms = samples.length ? Math.sqrt(sum / samples.length) : 0;
  const db = (value: number) =>
    value > 0 ? 20 * Math.log10(value) : -Infinity;
  return { rms: db(rms), peak: db(peak) };
}

/** 0–1 bar length for a level meter spanning −60 to 0 dBFS. */
export function meterFraction(dbfs: number): number {
  return Number.isFinite(dbfs) ? Math.min(1, Math.max(0, (dbfs + 60) / 60)) : 0;
}

export class LiveListener {
  private context: AudioContext | null = null;
  private gain: GainNode | null = null;
  private abort: AbortController | null = null;
  private next = 0;

  constructor(
    private readonly onLevel: (value: { rms: number; peak: number }) => void,
  ) {}

  /** Start from a click (browsers allow sound only after one). Resolves when it ends. */
  async start(volume: number, denoise = true): Promise<void> {
    this.stop();
    const context = new AudioContext({ sampleRate: SAMPLE_RATE });
    await context.resume();
    const gain = context.createGain();
    gain.gain.value = volume;
    gain.connect(context.destination);
    const abort = new AbortController();
    Object.assign(this, { context, gain, abort, next: 0 });
    const response = await fetch(`${LISTEN_URL}?denoise=${denoise}`, {
      signal: abort.signal,
      cache: "no-store",
    });
    if (!response.ok || !response.body) {
      const detail = await response.json().catch(() => null);
      this.stop();
      throw new Error(
        detail?.detail ?? "Live sound is not available right now.",
      );
    }
    const reader = response.body.getReader();
    let carry: Uint8Array | null = null;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done || this.abort !== abort) break;
        const { samples, rest } = pcmToFloat(value, carry);
        carry = rest;
        if (samples.length) this.play(samples);
      }
    } catch (error) {
      if (!abort.signal.aborted) throw error;
    } finally {
      if (this.abort === abort) this.stop();
    }
  }

  setVolume(volume: number): void {
    if (this.gain) this.gain.gain.value = volume;
  }

  stop(): void {
    this.abort?.abort();
    this.abort = null;
    void this.context?.close().catch(() => undefined);
    this.context = null;
    this.gain = null;
    this.onLevel({ rms: -Infinity, peak: -Infinity });
  }

  get listening(): boolean {
    return this.context !== null;
  }

  private play(samples: Float32Array<ArrayBuffer>): void {
    const context = this.context;
    if (!context || !this.gain) return;
    this.onLevel(level(samples));
    const buffer = context.createBuffer(1, samples.length, SAMPLE_RATE);
    buffer.copyToChannel(samples, 0);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    // Keep a small lead; if playback fell behind (tab asleep), jump to near-live.
    const now = context.currentTime;
    if (this.next < now || this.next > now + 3) this.next = now + LEAD_SECONDS;
    source.start(this.next);
    this.next += buffer.duration;
  }
}

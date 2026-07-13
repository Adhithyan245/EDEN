// Voice playback: browser SpeechSynthesis (fallback) and server audio (ElevenLabs).

export interface SpeechCallbacks {
  onStart?: () => void;
  onEnd?: () => void;
}

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
  // Prefer a deeper/en voice if available.
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find((v) => /en-GB|Daniel|Google UK English Male/i.test(v.name));
  if (preferred) utter.voice = preferred;
  utter.onstart = () => cb.onStart?.();
  utter.onend = () => cb.onEnd?.();
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
    audio.onplay = () => cb.onStart?.();
    audio.onended = () => {
      cb.onEnd?.();
      URL.revokeObjectURL(url);
    };
    void audio.play();
  } catch {
    cb.onStart?.();
    cb.onEnd?.();
  }
}

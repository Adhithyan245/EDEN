// Composer — a minimal, auto-hiding input, now with real voice capture.
//
// Root cause of "EDEN never responds when spoken to": there was no microphone
// capture anywhere in the frontend. This component only ever sent typed text;
// the placeholder "Speak to EDEN…" was aspirational, not functional. This adds
// real capture via the Web Speech API (SpeechRecognition, Chrome-only) behind
// a mic toggle, reusing the existing working `onSend` → `user_message` path
// unchanged — nothing on the backend needed to change for input to work.

import { useEffect, useRef, useState } from "react";

interface Props {
  connected: boolean;
  presence: string;
  onSend: (text: string) => void;
  onListening?: (active: boolean) => void;
}

type SpeechRecognitionCtor = new () => any;

const RecognitionCtor: SpeechRecognitionCtor | undefined =
  typeof window !== "undefined"
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined;

export default function Composer({ connected, presence, onSend, onListening }: Props) {
  const [value, setValue] = useState("");
  const [micOn, setMicOn] = useState(false);
  // Why voice can't run right now, shown above the bar. Without this every
  // failure was silent and the mic just looked dead.
  const [notice, setNotice] = useState("");
  const recognitionRef = useRef<any>(null);
  // Whether the mic *should* be running — separate from micOn so onend can
  // tell a deliberate stop from the browser silently ending an utterance.
  const wantListeningRef = useRef(false);
  // `rec.onend` is assigned once, inside startMic — a plain closure over the
  // `presence` prop there would freeze on whatever value it was at mic-start
  // time. Route it through a ref kept current every render instead, so the
  // restart check always sees the live value. Without this the mic can
  // auto-restart itself *while EDEN is speaking* and pick up her own voice
  // through the room speakers as if it were a new user turn — reproduced live
  // during testing: it built into a runaway self-conversation loop.
  const presenceRef = useRef(presence);
  presenceRef.current = presence;

  const submit = (spoken?: string) => {
    const text = (spoken ?? value).trim();
    if (!text) return;
    onSend(text);
    setValue("");
  };

  // EDEN's own voice plays back through the room speakers. If the mic stayed
  // hot while she spoke, it would hear itself and treat that as user input.
  // Pause recognition for the duration of "speaking" and resume right after.
  useEffect(() => {
    const rec = recognitionRef.current;
    if (!rec) return;
    if (presence === "speaking") {
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    } else if (wantListeningRef.current) {
      try {
        rec.start();
      } catch {
        /* already running */
      }
    }
  }, [presence]);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        /* noop */
      }
    };
  }, []);

  const stopMic = () => {
    wantListeningRef.current = false;
    setMicOn(false);
    onListening?.(false);
    try {
      recognitionRef.current?.stop();
    } catch {
      /* noop */
    }
  };

  const startMic = () => {
    if (!RecognitionCtor) {
      setNotice("Voice input needs Chrome or Edge. You can still type to EDEN.");
      return;
    }
    setNotice("");
    const rec = new RecognitionCtor();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = "en-US";

    rec.onresult = (e: any) => {
      // Belt-and-suspenders against the feedback loop described above:
      // stop() is not instantaneous, so a result already in flight can land
      // just after EDEN starts speaking. Drop it rather than treat her own
      // voice as a new turn.
      if (presenceRef.current === "speaking") return;
      const result = e.results[e.results.length - 1];
      if (result && result.isFinal) {
        const text = String(result[0]?.transcript ?? "").trim();
        if (text) submit(text);
      }
    };

    rec.onerror = (e: any) => {
      // Permission denied or the browser blocked mic access outright — give up
      // and fall back to typing rather than retry forever.
      if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
        stopMic();
        setNotice("Microphone blocked. Allow it from the icon in the address bar, then tap the mic again.");
      } else if (e?.error === "audio-capture") {
        stopMic();
        setNotice("No microphone found. Plug one in, or type to EDEN.");
      } else if (e?.error === "network") {
        // Brave and other Chromium forks expose the API but can't reach
        // Google's speech service, so this fails on every restart — without
        // stopping here onend would retry in a silent loop forever.
        stopMic();
        setNotice("Voice input isn't available in this browser. Try Chrome or Edge, or type to EDEN.");
      }
      // Other errors ("no-speech", "aborted") are routine; onend below
      // decides whether to restart.
    };

    rec.onend = () => {
      // The API stops after a pause even in continuous mode — restart it
      // automatically as long as the user hasn't turned the mic off and
      // EDEN isn't mid-speech. Must read presenceRef (live), not the
      // `presence` prop closed over at mic-start time — see note above.
      if (wantListeningRef.current && presenceRef.current !== "speaking") {
        try {
          rec.start();
        } catch {
          /* already running */
        }
      }
    };

    recognitionRef.current = rec;
    wantListeningRef.current = true;
    setMicOn(true);
    onListening?.(true);
    try {
      rec.start();
    } catch {
      /* noop */
    }
  };

  const toggleMic = () => (micOn ? stopMic() : startMic());

  return (
    <div className="absolute inset-x-0 bottom-7 flex flex-col items-center gap-2 px-6">
      {notice && <div className="max-w-xl text-center text-xs text-amber-200/80">{notice}</div>}
      <div
        className={`flex w-full max-w-xl items-center gap-3 rounded-full border border-white/10 bg-white/[0.03] px-5 py-3 backdrop-blur-md transition duration-300 hover:opacity-100 focus-within:border-cyan-400/40 focus-within:bg-white/[0.06] focus-within:opacity-100 ${
          presence === "off" ? "opacity-80" : "opacity-40"
        }`}
      >
        <span
          className="h-1.5 w-1.5 flex-shrink-0 rounded-full transition"
          style={{ background: connected ? "#34d399" : "#fbbf24", boxShadow: connected ? "0 0 8px #34d399" : "none" }}
          title={connected ? "online" : "reconnecting…"}
        />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={micOn ? "Listening… just talk" : "Type to EDEN, or tap the mic to talk"}
          className="flex-1 bg-transparent text-sm text-white/90 outline-none placeholder:text-white/40"
        />
        <button
          onClick={toggleMic}
          className="flex-shrink-0 transition hover:text-cyan-200"
          style={{ color: micOn ? "#5eead4" : "rgba(255,255,255,0.6)" }}
          aria-label={micOn ? "Stop listening" : "Start listening"}
          title={micOn ? "Stop listening" : "Tap to talk"}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill={micOn ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10a7 7 0 0 0 14 0M12 17v5" />
          </svg>
        </button>
        <button
          onClick={() => submit()}
          className="flex-shrink-0 text-white/40 transition hover:text-cyan-200"
          aria-label="Send"
        >
          ↵
        </button>
      </div>
    </div>
  );
}

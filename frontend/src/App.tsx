import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { WS_URL } from "./config";
import { EdenSocket } from "./lib/socket";
import type { EdenEvent, EdenState } from "./lib/events";
import { playAudioB64, speakBrowser } from "./lib/audio";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

interface Meta {
  connected: boolean;
  mode: string;
  llm: string;
  tts: string;
}

export default function App() {
  const [state, setState] = useState<EdenState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [meta, setMeta] = useState<Meta>({ connected: false, mode: "—", llm: "—", tts: "—" });

  const socketRef = useRef<EdenSocket | null>(null);
  const streamingRef = useRef<boolean>(false);

  useEffect(() => {
    const socket = new EdenSocket(
      WS_URL,
      handleEvent,
      (connected) => setMeta((m) => ({ ...m, connected })),
    );
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleEvent(ev: EdenEvent) {
    switch (ev.type) {
      case "ready":
        setMeta((m) => ({ ...m, mode: ev.mode, llm: ev.llm, tts: ev.tts }));
        break;
      case "state":
        setState(ev.state);
        break;
      case "token":
        appendToken(ev.text);
        break;
      case "reply_done":
        streamingRef.current = false;
        break;
      case "speak":
        speakBrowser(ev.text, {
          onStart: () => setState("speaking"),
          onEnd: () => setState("idle"),
        });
        break;
      case "speech_audio":
        playAudioB64(ev.audio_b64, ev.mime, {
          onStart: () => setState("speaking"),
          onEnd: () => setState("idle"),
        });
        break;
      case "error":
        appendAssistantLine(`[error] ${ev.message}`);
        break;
    }
  }

  function appendToken(text: string) {
    setMessages((prev) => {
      const next = [...prev];
      if (!streamingRef.current || next.length === 0 || next[next.length - 1].role !== "assistant") {
        next.push({ role: "assistant", text: "" });
      }
      streamingRef.current = true;
      next[next.length - 1] = {
        role: "assistant",
        text: next[next.length - 1].text + text,
      };
      return next;
    });
  }

  function appendAssistantLine(text: string) {
    streamingRef.current = false;
    setMessages((prev) => [...prev, { role: "assistant", text }]);
  }

  function send() {
    const text = input.trim();
    if (!text || !socketRef.current) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    streamingRef.current = false;
    socketRef.current.send({ type: "user_message", text });
    setInput("");
  }

  return (
    <div className="flex h-full w-full items-stretch gap-6 p-6">
      {/* Left: avatar + status */}
      <div className="flex w-[360px] flex-col gap-6">
        <div className="glass flex flex-1 flex-col items-center justify-center">
          <Orb state={state} />
          <div className="mt-6 font-mono text-xs uppercase tracking-[0.3em] text-cyan-300/80">
            {state}
          </div>
        </div>
        <div className="glass p-5">
          <h2 className="mb-3 font-mono text-[11px] uppercase tracking-[0.25em] text-white/50">
            System Status
          </h2>
          <StatusRow label="Link" value={meta.connected ? "online" : "reconnecting…"} ok={meta.connected} />
          <StatusRow label="Mode" value={meta.mode} ok />
          <StatusRow label="Reasoning" value={meta.llm} ok />
          <StatusRow label="Voice" value={meta.tts} ok />
        </div>
      </div>

      {/* Right: conversation */}
      <div className="glass flex flex-1 flex-col">
        <div className="border-b border-white/10 px-6 py-4">
          <div className="font-mono text-sm tracking-[0.35em] text-cyan-200">E · D · E · N</div>
          <div className="text-xs text-white/40">Everything Done Effortlessly, Naturally</div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
          {messages.length === 0 && (
            <div className="mt-10 text-center text-sm text-white/30">
              Say something to EDEN. (Voice input arrives on Day 2 — type for now.)
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} role={m.role} text={m.text} />
          ))}
        </div>

        <div className="flex items-center gap-3 border-t border-white/10 px-6 py-4">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Message EDEN…"
            className="flex-1 rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-none placeholder:text-white/30 focus:border-cyan-400/50"
          />
          <button
            onClick={send}
            className="rounded-xl border border-cyan-400/40 bg-cyan-400/10 px-5 py-3 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/20"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-white/45">{label}</span>
      <span className={`font-mono ${ok ? "text-cyan-200" : "text-amber-300"}`}>{value}</span>
    </div>
  );
}

function Bubble({ role, text }: { role: "user" | "assistant"; text: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "border border-white/10 bg-white/10 text-white"
            : "border border-cyan-400/20 bg-cyan-400/5 text-cyan-50"
        }`}
      >
        {text || "…"}
      </div>
    </div>
  );
}

/** Placeholder reactive core — upgraded to a Three.js orb on Day 2. */
function Orb({ state }: { state: EdenState }) {
  const active = state !== "idle";
  const color =
    state === "thinking" ? "#a855f7" : state === "speaking" ? "#22d3ee" : state === "listening" ? "#34d399" : "#38bdf8";
  return (
    <motion.div
      className="relative flex items-center justify-center"
      style={{ width: 180, height: 180 }}
    >
      <motion.div
        className="absolute rounded-full"
        style={{ width: 180, height: 180, background: color, filter: "blur(40px)", opacity: 0.35 }}
        animate={{ scale: active ? [1, 1.15, 1] : [1, 1.05, 1], opacity: active ? [0.35, 0.55, 0.35] : [0.2, 0.3, 0.2] }}
        transition={{ duration: active ? 1.1 : 3, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="rounded-full border"
        style={{ width: 120, height: 120, borderColor: color, boxShadow: `0 0 60px ${color}` }}
        animate={{ scale: active ? [1, 1.08, 1] : 1 }}
        transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
      />
    </motion.div>
  );
}

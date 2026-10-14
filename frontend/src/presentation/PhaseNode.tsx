// PhaseNode — one node in the build constellation.
//
// A phase is a point of light on a vertical thread: dim when pending, brightening
// and pulsing while active, steady when done, cooled when failed. This is the
// visual replacement for terminal logs.

import { motion } from "framer-motion";

import type { Phase } from "./state/presentation";

const COLORS = {
  pending: "rgba(255,255,255,0.28)",
  active: "#67e8f9",
  done: "#34d399",
  failed: "#fb7185",
};

export default function PhaseNode({ phase, color }: { phase: Phase; color: string }) {
  const c = phase.status === "active" ? color : COLORS[phase.status];
  const bright = phase.status === "active" || phase.status === "done";

  return (
    <div className="flex items-center gap-4">
      <div className="relative flex h-4 w-4 items-center justify-center">
        {phase.status === "active" && (
          <motion.span
            className="absolute rounded-full"
            style={{ width: 16, height: 16, background: c }}
            animate={{ scale: [1, 2.1, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        <motion.span
          className="relative rounded-full"
          style={{ background: c }}
          animate={{
            width: bright ? 10 : 7,
            height: bright ? 10 : 7,
            boxShadow: bright ? `0 0 14px ${c}` : "none",
          }}
          transition={{ duration: 0.5 }}
        />
      </div>
      <motion.span
        className="text-sm tracking-wide"
        animate={{
          color:
            phase.status === "pending"
              ? "rgba(230,241,255,0.35)"
              : phase.status === "failed"
              ? "rgba(251,113,133,0.9)"
              : "rgba(230,241,255,0.92)",
          opacity: 1,
        }}
        transition={{ duration: 0.5 }}
      >
        {phase.label}
      </motion.span>
    </div>
  );
}

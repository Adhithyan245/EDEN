// AccessGate — asks for the access code when the backend requires one.
//
// Only appears after the backend closes the socket with 4401 (a public
// deployment with EDEN_ACCESS_CODE set). Local development never sees it.

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";

interface Props {
  open: boolean;
  rejected: boolean;          // a code was tried and refused
  onSubmit: (code: string) => void;
}

export default function AccessGate({ open, rejected, onSubmit }: Props) {
  const [code, setCode] = useState("");
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-20 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <form
            className="w-full max-w-sm text-center"
            onSubmit={(e) => {
              e.preventDefault();
              if (code.trim()) onSubmit(code.trim());
            }}
          >
            <div className="mb-2 text-[10px] uppercase tracking-[0.4em] text-white/40">Access code</div>
            <div className="mb-6 text-sm font-light text-white/60">
              This EDEN is private. Enter the code you were given.
            </div>
            <input
              autoFocus
              type="password"
              autoComplete="off"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded-full border border-white/15 bg-white/[0.04] px-5 py-3 text-center text-white/90 outline-none transition focus:border-white/40"
              aria-label="Access code"
            />
            {rejected && <div className="mt-3 text-xs text-rose-300/80">That code didn't work.</div>}
            <button
              type="submit"
              className="mt-5 rounded-full border border-white/20 px-6 py-2 text-xs uppercase tracking-[0.3em] text-white/70 transition hover:border-white/45 hover:text-white"
            >
              Enter
            </button>
          </form>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

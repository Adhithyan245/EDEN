// Clarification — EDEN's single question, shown gently above the composer.
//
// Appears when the backend emits clarification_requested and clears once the
// user answers. Composed and quiet, never a modal or an alert.

import { AnimatePresence, motion } from "framer-motion";

export default function Clarification({ question }: { question: string | null }) {
  return (
    <AnimatePresence>
      {question && (
        <motion.div
          className="pointer-events-none absolute inset-x-0 bottom-[26vh] flex justify-center px-8"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.5 }}
        >
          <div className="max-w-2xl text-center">
            <div className="mb-1 text-[10px] uppercase tracking-[0.4em] text-cyan-300/45">
              A quick question
            </div>
            <div className="text-xl font-light text-cyan-50/90">{question}</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

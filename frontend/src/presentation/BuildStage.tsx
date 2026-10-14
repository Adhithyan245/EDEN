// BuildStage — the cinematic progress environment shown while EDEN builds/edits.
//
// It renders the plan as a quiet constellation of phases lighting up in sequence,
// off to one side so EDEN's presence stays centre stage. Never a terminal.

import { AnimatePresence, motion } from "framer-motion";

import PhaseNode from "./PhaseNode";
import type { Phase } from "./state/presentation";

interface Props {
  visible: boolean;
  appName: string | null;
  mode: "build" | "edit" | null;
  phases: Phase[];
  color: string;
  // --- optional completion location (additive; backward compatible) ---
  // Newer backends report where the finished project was saved to disk
  // (`workspace`); older ones reported the dev-server `url` it launched.
  // Neither implies a running server — this is display-only.
  workspace?: string | null;
  url?: string | null;
}

export default function BuildStage({ visible, appName, mode, phases, color, workspace, url }: Props) {
  const location = workspace ?? url ?? null;
  const allDone = phases.length > 0 && phases.every((p) => p.status === "done");

  return (
    <AnimatePresence>
      {visible && phases.length > 0 && (
        <motion.div
          className="pointer-events-none absolute right-[6vw] top-1/2 -translate-y-1/2"
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 24 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        >
          <div className="mb-5">
            <div className="text-[10px] uppercase tracking-[0.4em] text-white/35">
              {mode === "edit" ? "Refining" : "Building"}
            </div>
            {appName && (
              <div className="mt-1 text-lg font-light tracking-wide text-white/90">{appName}</div>
            )}
          </div>

          <div className="relative flex flex-col gap-5 pl-[7px]">
            {/* thread connecting the nodes */}
            <div
              className="absolute left-[7px] top-2 bottom-2 w-px"
              style={{ background: "linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.14), rgba(255,255,255,0.06))" }}
            />
            {phases.map((p) => (
              <PhaseNode key={p.id} phase={p} color={color} />
            ))}
          </div>

          {/* Completion location — the project is saved, not served. */}
          <AnimatePresence>
            {allDone && location && (
              <motion.div
                className="mt-5 max-w-[26vw] pl-[7px]"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.6, ease: "easeOut" }}
              >
                <div className="text-[10px] uppercase tracking-[0.4em] text-white/35">
                  Project saved to
                </div>
                <div
                  className="mt-1 truncate text-sm font-light tracking-wide text-white/70"
                  title={location}
                >
                  {location}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

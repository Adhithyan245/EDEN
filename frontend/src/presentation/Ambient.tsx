// Ambient — the minimal cinematic environment behind EDEN.
//
// A deep gradient and one very soft, slowly drifting glow whose hue follows
// EDEN's colour. No particles, no distractions — just atmosphere. Darkens
// almost to black when EDEN is off/asleep.

import { motion } from "framer-motion";

interface Props {
  color: string;
  awake: boolean;
  active: boolean; // thinking / building / speaking → slightly more presence
}

export default function Ambient({ color, awake, active }: Props) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* Base vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(1400px 900px at 50% 8%, #0a1120 0%, #05070d 55%, #020309 100%)",
        }}
      />
      {/* Soft coloured ambient glow */}
      <motion.div
        className="absolute left-1/2 top-1/2 rounded-full"
        style={{
          width: "70vmax",
          height: "70vmax",
          x: "-50%",
          y: "-50%",
          background: `radial-gradient(circle at 50% 50%, ${color} 0%, transparent 60%)`,
          filter: "blur(120px)",
        }}
        initial={{ opacity: 0 }}
        animate={{
          opacity: awake ? (active ? 0.16 : 0.09) : 0.02,
          scale: [1, 1.06, 1],
        }}
        transition={{
          opacity: { duration: 1.4 },
          scale: { duration: 14, repeat: Infinity, ease: "easeInOut" },
        }}
      />
      {/* Faint top-edge horizon line for depth */}
      <motion.div
        className="absolute inset-x-0 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }}
        initial={{ opacity: 0 }}
        animate={{ opacity: awake ? 0.18 : 0 }}
        transition={{ duration: 1.4 }}
      />
    </div>
  );
}

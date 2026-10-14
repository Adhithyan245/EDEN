// Presence — EDEN's abstract luminous "face".
//
// Not a humanoid face (honoring the locked blueprint decision) but a living
// presence: a glowing core with two light "eyes" that widen with attention,
// narrow while reasoning, and flex with the voice. Expression is conveyed by
// glow, aperture, colour, and micro-motion — never a cartoon mouth.
//
// Performance: the emotion/presence colour transitions are low-frequency and use
// Framer springs; the per-frame values (voice amplitude, breathing, blink) are
// driven by motion values updated inside useAnimationFrame / animate(), so React
// never re-renders per frame.

import { useEffect, useMemo } from "react";
import { AnimatePresence, animate, motion, useAnimationFrame, useMotionValue, useSpring, useTransform } from "framer-motion";

import { audioBus } from "../lib/audio";
import { colorFor, type Presence as PresenceState } from "./state/presentation";
import type { EdenEmotion } from "../lib/events";

interface Props {
  presence: PresenceState;
  emotion: EdenEmotion;
  pulseType: "success" | "concern" | null;
  pulseId: number;
}

// Per-presence targets for eye openness and glow strength.
const OPEN: Record<PresenceState, number> = {
  off: 0, idle: 0.55, listening: 1, thinking: 0.42, speaking: 0.62,
};
const GLOW: Record<PresenceState, number> = {
  off: 0, idle: 0.5, listening: 0.85, thinking: 0.7, speaking: 0.72,
};

export default function Presence({ presence, emotion, pulseType, pulseId }: Props) {
  const color = useMemo(() => colorFor(presence, emotion), [presence, emotion]);

  // Per-frame motion values (no re-renders).
  const amp = useMotionValue(0);          // live voice amplitude 0..1
  const openness = useMotionValue(OPEN[presence]);
  const glow = useMotionValue(GLOW[presence]);
  const blink = useMotionValue(1);        // 1 open, dips to ~0 on a blink
  const bloom = useMotionValue(0);         // one-shot success/concern bloom

  // Smooth the presence-driven targets.
  const opennessS = useSpring(openness, { stiffness: 120, damping: 18 });
  const glowS = useSpring(glow, { stiffness: 90, damping: 20 });

  useEffect(() => {
    openness.set(OPEN[presence]);
    glow.set(GLOW[presence]);
  }, [presence, openness, glow]);

  // Voice amplitude + synthetic pulse while speaking with no analyser data.
  useAnimationFrame((t) => {
    let a = audioBus.amplitude;
    if (audioBus.speaking && a < 0.03) {
      a = 0.12 + 0.1 * (0.5 + 0.5 * Math.sin(t / 140)); // gentle synthetic breath
    }
    amp.set(a);
  });

  // Occasional, natural blink while awake.
  useEffect(() => {
    if (presence === "off") return;
    let alive = true;
    const loop = () => {
      if (!alive) return;
      const next = 2800 + Math.random() * 4200;
      window.setTimeout(async () => {
        if (!alive) return;
        await animate(blink, 0.08, { duration: 0.07, ease: "easeIn" });
        await animate(blink, 1, { duration: 0.12, ease: "easeOut" });
        loop();
      }, next);
    };
    loop();
    return () => { alive = false; };
  }, [presence, blink]);

  // One-shot bloom on success / concern.
  useEffect(() => {
    if (!pulseType) return;
    (async () => {
      await animate(bloom, 1, { duration: 0.35, ease: "easeOut" });
      await animate(bloom, 0, { duration: 1.1, ease: "easeInOut" });
    })();
  }, [pulseId, pulseType, bloom]);

  // Derived transforms.
  const eyeScaleY = useTransform([opennessS, amp, blink] as any, ([o, a, b]: number[]) =>
    Math.max(0.04, (o + a * 0.5) * b));
  const glowOpacity = useTransform([glowS, amp, bloom] as any, ([g, a, bl]: number[]) =>
    Math.min(1, g + a * 0.5 + bl * 0.4));
  const glowScale = useTransform([glowS, amp, bloom] as any, ([g, a, bl]: number[]) =>
    0.9 + g * 0.15 + a * 0.25 + bl * 0.35);
  const ringScale = useTransform(amp, (a) => 1 + a * 0.06);

  const smile = pulseType === "success";
  const concernArc = pulseType === "concern" || emotion === "concerned";

  return (
    <div className="relative flex items-center justify-center" style={{ width: "min(46vmin, 460px)", height: "min(46vmin, 460px)" }}>
      {/* Soft outer bloom */}
      <motion.div
        aria-hidden
        className="absolute rounded-full"
        initial={false}
        style={{
          width: "100%", height: "100%",
          background: `radial-gradient(circle at 50% 50%, ${color} 0%, transparent 62%)`,
          opacity: glowOpacity, scale: glowScale, filter: "blur(28px)",
        }}
        animate={{ background: `radial-gradient(circle at 50% 50%, ${color} 0%, transparent 62%)` }}
        transition={{ duration: 0.8 }}
      />

      {/* Breathing core ring + eyes */}
      <motion.svg
        viewBox="0 0 400 400"
        className="relative"
        style={{ width: "72%", height: "72%", scale: ringScale }}
        animate={{ scale: presence === "off" ? 0.9 : [1, 1.02, 1] }}
        transition={{ duration: presence === "idle" ? 6 : 4, repeat: Infinity, ease: "easeInOut" }}
      >
        <motion.circle
          cx={200} cy={200} r={150}
          fill="none" strokeWidth={1.5}
          initial={{ opacity: 0 }}
          animate={{ stroke: color, opacity: presence === "off" ? 0 : 0.35 }}
          transition={{ duration: 0.8 }}
        />
        <motion.circle
          cx={200} cy={200} r={118}
          fill="none" strokeWidth={2}
          initial={{ opacity: 0 }}
          animate={{ stroke: color, opacity: presence === "off" ? 0 : 0.6 }}
          transition={{ duration: 0.8 }}
          style={{ filter: `drop-shadow(0 0 10px ${color})` }}
        />

        {/* Eyes — two light apertures. Vertical aperture = attention + voice. */}
        <g>
          {[150, 250].map((cx) => (
            <motion.rect
              key={cx}
              x={cx - 34} y={200 - 42}
              width={68} height={84} rx={30}
              initial={false}
              style={{ scaleY: eyeScaleY, transformOrigin: `${cx}px 200px`, filter: `drop-shadow(0 0 12px ${color})` }}
              animate={{ fill: color }}
              transition={{ duration: 0.8 }}
            />
          ))}
        </g>

        {/* Expression arc — a faint smile of light on success, a soft dip on concern. */}
        <AnimatePresence>
          {smile && (
            <motion.path
              key="smile"
              d="M150 270 Q200 300 250 270"
              fill="none" stroke={color} strokeWidth={4} strokeLinecap="round"
              initial={{ opacity: 0 }} animate={{ opacity: 0.7 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              style={{ filter: `drop-shadow(0 0 8px ${color})` }}
            />
          )}
          {concernArc && !smile && (
            <motion.path
              key="concern"
              d="M156 286 Q200 268 244 286"
              fill="none" stroke={color} strokeWidth={3} strokeLinecap="round"
              initial={{ opacity: 0 }} animate={{ opacity: 0.5 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
            />
          )}
        </AnimatePresence>
      </motion.svg>

      {/* Reasoning: a single point of energy orbiting the core (never a spinner). */}
      <AnimatePresence>
        {presence === "thinking" && (
          <motion.div
            className="absolute"
            style={{ width: "72%", height: "72%" }}
            initial={{ opacity: 0 }} animate={{ opacity: 1, rotate: 360 }} exit={{ opacity: 0 }}
            transition={{ rotate: { duration: 3.2, repeat: Infinity, ease: "linear" }, opacity: { duration: 0.6 } }}
          >
            <div
              className="absolute left-1/2 top-0 h-2.5 w-2.5 -translate-x-1/2 rounded-full"
              style={{ background: color, boxShadow: `0 0 14px ${color}` }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

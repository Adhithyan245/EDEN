// Captions — EDEN's words, shown as minimal cinematic subtitles.
//
// Two display modes:
//
//   chat / default  — single-line cinematic subtitle, centred low on screen,
//                     fades in as it streams, fades out when idle. Unchanged
//                     from the original implementation.
//
//   information     — expanded glass panel that scrolls long research answers
//                     and lists clickable sources beneath them. Slides up from
//                     the bottom with the same motion language as the subtitle.
//
// Priority: displayResponse (completed turn) → text (streaming caption).
// Sources are only shown in information mode and when sources.length > 0.

import { AnimatePresence, motion } from "framer-motion";

interface Source {
  title: string;
  url: string;
  snippet?: string;
}

interface Props {
  // --- existing props (unchanged) ---
  text: string;
  suggestion: string | null;
  visible: boolean;
  // --- new structured response props ---
  displayResponse?: string;
  responseMode?: "chat" | "information" | "build" | "task" | "error";
  sources?: Source[];
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="mt-4 border-t border-white/10 pt-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-white/30">
        Sources
      </p>
      <ul className="space-y-2">
        {sources.map((src, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className="mt-[3px] text-xs text-cyan-400/50">↗</span>
            <div className="min-w-0">
              <a
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate text-sm font-medium text-cyan-300/80 underline-offset-2 hover:text-cyan-200 hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
              >
                {src.title || src.url}
              </a>
              {src.snippet && (
                <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-white/40">
                  {src.snippet}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function InformationPanel({
  content,
  sources = [],
}: {
  content: string;
  sources?: Source[];
}) {
  return (
    <motion.div
      key="info-panel"
      className="pointer-events-auto w-full max-w-2xl"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Glass card */}
      <div
        className="rounded-2xl px-6 py-5"
        style={{
          background: "rgba(8, 18, 36, 0.72)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: "0 8px 48px rgba(0,0,0,0.5), 0 0 0 0.5px rgba(255,255,255,0.04) inset",
        }}
      >
        {/* Response body — scrollable if very long */}
        <div
          className="max-h-[38vh] overflow-y-auto pr-1 text-sm font-light leading-relaxed text-white/85 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          style={{ textShadow: "0 1px 12px rgba(0,0,0,0.4)" }}
        >
          {/* Render line-breaks from the response as proper paragraphs */}
          {content.split(/\n\n+/).map((para, i) => (
            <p key={i} className={i > 0 ? "mt-3" : ""}>
              {para.replace(/\n/g, " ")}
            </p>
          ))}
        </div>

        <SourceList sources={sources} />
      </div>
    </motion.div>
  );
}

function ErrorBanner({ content }: { content: string }) {
  return (
    <motion.div
      key="error-banner"
      className="pointer-events-auto w-full max-w-xl"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div
        className="rounded-xl px-5 py-3 text-center text-sm font-light text-rose-200/90"
        style={{
          background: "rgba(120, 20, 30, 0.55)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(251, 113, 133, 0.2)",
        }}
      >
        {content}
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Captions({
  text,
  suggestion,
  visible,
  displayResponse,
  responseMode = "chat",
  sources = [],
}: Props) {
  // The completed structured response takes priority over a streaming caption.
  const content = displayResponse || text;
  const isInformation = responseMode === "information" && !!displayResponse;
  const isError = responseMode === "error" && !!displayResponse;
  // For build/task modes the captions area stays out of the way — those modes
  // have their own build stage UI. Chat falls through to the cinematic caption.
  const isCinematic = !isInformation && !isError;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-[10vh] flex flex-col items-center gap-3 px-6">

      {/* Information panel (research responses) */}
      <AnimatePresence>
        {isInformation && (
          <InformationPanel content={content} sources={sources} />
        )}
      </AnimatePresence>

      {/* Error banner */}
      <AnimatePresence>
        {isError && (
          <ErrorBanner content={content} />
        )}
      </AnimatePresence>

      {/* Cinematic subtitle (chat mode + streaming captions) */}
      <AnimatePresence>
        {isCinematic && visible && content && (
          <motion.p
            key="caption"
            className="max-w-3xl text-center text-2xl font-light leading-relaxed text-white/90"
            style={{ textShadow: "0 2px 30px rgba(0,0,0,0.6)" }}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.5 }}
          >
            {content}
          </motion.p>
        )}
      </AnimatePresence>

      {/* Suggestion line — always beneath whatever is showing */}
      <AnimatePresence>
        {suggestion && (
          <motion.p
            className="max-w-2xl text-center text-sm font-light italic text-cyan-200/60"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
          >
            {suggestion}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
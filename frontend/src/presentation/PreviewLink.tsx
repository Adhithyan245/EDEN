// PreviewLink — a quiet, persistent link to the app EDEN last compiled.
//
// The backend serves each compiled build as static files at /preview/<id>/.
// The link outlives the build constellation (which retires on idle) so the
// audience can open the result whenever they like.

import { AnimatePresence, motion } from "framer-motion";

import { HTTP_BASE } from "../config";
import type { PresentationState } from "./state/presentation";

export default function PreviewLink({ preview }: { preview: PresentationState["preview"] }) {
  const href = preview ? `${HTTP_BASE}${preview.url}?v=${preview.version}` : "";
  return (
    <AnimatePresence>
      {preview && (
        <motion.a
          key={preview.url}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="absolute right-4 top-4 max-w-[calc(100vw-2rem)] rounded-full border border-white/15 bg-white/[0.04] px-4 py-2 text-xs font-light tracking-[0.2em] text-white/70 transition hover:border-white/35 hover:text-white sm:right-[6vw] sm:top-[5vh]"
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        >
          <span className="uppercase">Open</span>{" "}
          <span className="tracking-wide text-white/90">{preview.appName ?? "app"}</span> ↗
        </motion.a>
      )}
    </AnimatePresence>
  );
}

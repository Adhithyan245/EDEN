// Stage — the full-bleed cinematic scene. No panels, no dashboards: only EDEN.
//
// Everything here is a pure function of presentation state. The layers, back to
// front: ambient environment, the awakening reveal, EDEN's presence, the build
// constellation, captions, the clarification prompt, and the minimal composer.

import { AnimatePresence, motion } from "framer-motion";

import Ambient from "./Ambient";
import BuildStage from "./BuildStage";
import Captions from "./Captions";
import Clarification from "./Clarification";
import Composer from "./Composer";
import Presence from "./Presence";
import PreviewLink from "./PreviewLink";
import { colorFor, type PresentationState } from "./state/presentation";

interface Props {
  state: PresentationState;
  onSend: (text: string) => void;
  onListening: (active: boolean) => void;
}

export default function Stage({ state, onSend, onListening }: Props) {
  const color = colorFor(state.presence, state.emotion);
  const active = state.presence === "thinking" || state.presence === "speaking" || state.building;
  const captionsVisible =
    state.presence === "speaking" || state.streaming || !!state.caption || !!state.displayResponse;

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      <Ambient color={color} awake={state.awake} active={active} />

      {/* Pre-wake monogram — the only thing in the dark before EDEN illuminates. */}
      <AnimatePresence>
        {!state.awake && (
          <motion.div
            className="absolute inset-0 flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.2 }}
          >
            <motion.div
              className="font-light tracking-[0.6em] text-white/20"
              style={{ fontSize: "clamp(18px, 3vmin, 34px)" }}
              animate={{ opacity: [0.12, 0.28, 0.12] }}
              transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut" }}
            >
              EDEN
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* EDEN's presence — fades up from black on awakening. */}
      <motion.div
        className="absolute inset-0 flex items-center justify-center"
        initial={{ opacity: 0, scale: 0.92, filter: "blur(12px)" }}
        animate={{ opacity: state.awake ? 1 : 0, scale: state.awake ? 1 : 0.92, filter: state.awake ? "blur(0px)" : "blur(12px)" }}
        transition={{ duration: 1.6, ease: [0.16, 1, 0.3, 1] }}
      >
        <Presence
          presence={state.presence}
          emotion={state.emotion}
          pulseType={state.pulseType}
          pulseId={state.pulseId}
        />
      </motion.div>

      <BuildStage
        visible={state.building}
        appName={state.appName}
        mode={state.buildMode}
        phases={state.phases}
        color={color}
      />

      <PreviewLink preview={state.preview} />

      <Captions
        text={state.caption}
        suggestion={state.suggestion}
        visible={captionsVisible}
        displayResponse={state.displayResponse}
        responseMode={state.responseMode}
        sources={state.sources}
      />
      <Clarification question={state.clarify} />

      <Composer
        connected={state.connected}
        presence={state.presence}
        onSend={onSend}
        onListening={onListening}
      />
    </div>
  );
}

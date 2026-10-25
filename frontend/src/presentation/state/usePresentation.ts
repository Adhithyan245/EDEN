// usePresentation — bridges the WebSocket event stream to presentation state.
//
// It owns one subtlety: the backend sends `state: idle` immediately after handing
// off audio (it does not wait for playback), so audio playback — not the backend
// state event — is the source of truth for how long EDEN is "speaking". While
// audio is playing we ignore backend state events; the audio's own start/end
// drives the speaking→idle transition.
//
// response_ready handling:
//   The backend sends a structured response_ready event that carries the full
//   display response, mode, and sources. This handler is DISPLAY-ONLY: it stores
//   that text for the UI and never triggers speech. Speech is driven solely by
//   the backend's speech_audio / speak events (see below), which are the single
//   source of truth for voice. Speaking here as well would produce two
//   simultaneous voices (browser SpeechSynthesis layered over ElevenLabs audio).

import { useCallback, useReducer, useRef } from "react";

import type { EdenEvent } from "../../lib/events";
import { audioBus, playAudioB64, speakBrowser } from "../../lib/audio";
import { Action, initialState, reduce } from "./presentation";

export function usePresentation() {
  const [state, dispatch] = useReducer(reduce, initialState);
  const speakingLock = useRef(false);
  const streamingRef = useRef(false);

  const setConnected = useCallback((connected: boolean) => {
    dispatch({ type: "@connected", connected });
  }, []);

  const ingest = useCallback((ev: EdenEvent) => {
    switch (ev.type) {
      case "speech_audio": {
        speakingLock.current = true;
        audioBus.resume();
        dispatch({ type: "state", state: "speaking" });
        playAudioB64(ev.audio_b64, ev.mime, {
          onEnd: () => {
            speakingLock.current = false;
            dispatch({ type: "state", state: "idle" });
          },
        });
        return;
      }

      // Streamed speech (Gemini): chunks play as they arrive; the audio
      // clock, not the backend, decides when EDEN stops speaking.
      case "speech_stream_start": {
        speakingLock.current = true;
        audioBus.resume();
        dispatch({ type: "state", state: "speaking" });
        const onEnd = () => {
          speakingLock.current = false;
          dispatch({ type: "state", state: "idle" });
        };
        streamingRef.current = audioBus.streamStart(ev.sample_rate, { onEnd });
        // No AudioWorklet in this browser: say the line with the built-in voice.
        if (!streamingRef.current) speakBrowser(ev.text, { onEnd });
        return;
      }

      case "speech_chunk":
        if (streamingRef.current) audioBus.streamChunk(ev.pcm_b64);
        return;

      case "speech_stream_end":
        if (streamingRef.current) audioBus.streamEnd();
        return;

      case "speak": {
        // Legacy TTS path — backend sends the full spoken string directly.
        speakingLock.current = true;
        dispatch({ type: "state", state: "speaking" });
        speakBrowser(ev.text, {
          onEnd: () => {
            speakingLock.current = false;
            dispatch({ type: "state", state: "idle" });
          },
        });
        return;
      }

      case "response_ready": {
        // Display-only. Store the response, mode, and sources for the UI.
        // Speech is intentionally NOT triggered here: the backend always follows
        // response_ready with exactly one speech event — speech_audio (ElevenLabs)
        // or speak (browser) — which is the single voice path. Speaking here too
        // would layer browser SpeechSynthesis over the ElevenLabs audio (two voices).
        dispatch({
          type: "response_ready",
          response: ev.response,
          voice_response: ev.voice_response,
          response_mode: ev.response_mode,
          sources: ev.sources ?? [],
        });
        return;
      }

      case "state": {
        // Audio owns the speaking window; ignore premature backend states.
        if (speakingLock.current) return;
        dispatch(ev as Action);
        return;
      }

      default:
        dispatch(ev as Action);
    }
  }, []);

  const dismissClarify = useCallback(() => dispatch({ type: "@dismissClarify" }), []);
  const userSpoke = useCallback(() => dispatch({ type: "@userSpoke" }), []);
  const setListening = useCallback(
    (active: boolean) => dispatch({ type: "@listening", active }),
    [],
  );

  return { state, ingest, dispatch, dismissClarify, userSpoke, setListening, setConnected };
}
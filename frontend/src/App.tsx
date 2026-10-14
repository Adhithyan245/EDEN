import { useEffect, useRef } from "react";

import { WS_URL } from "./config";
import { EdenSocket } from "./lib/socket";
import { audioBus } from "./lib/audio";
import Stage from "./presentation/Stage";
import { usePresentation } from "./presentation/state/usePresentation";

/**
 * EDEN is an event renderer. The socket streams typed events; usePresentation
 * turns them into presentation state; Stage draws that state cinematically.
 * There is no UI beyond EDEN.
 */
export default function App() {
  const { state, ingest, setConnected, userSpoke, setListening } = usePresentation();

  // ingest / setConnected are stable (useCallback []), so this connects once.
  const ingestRef = useRef(ingest);
  ingestRef.current = ingest;
  const connRef = useRef(setConnected);
  connRef.current = setConnected;

  const socketRef = useRef<EdenSocket | null>(null);

  useEffect(() => {
    const socket = new EdenSocket(
      WS_URL,
      (ev) => ingestRef.current(ev),
      (c) => connRef.current(c),
    );
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
  }, []);

  function onSend(text: string) {
    if (!socketRef.current) return;
    audioBus.resume(); // unlock the audio context on a user gesture
    userSpoke();
    socketRef.current.send({ type: "user_message", text });
  }

  return <Stage state={state} onSend={onSend} onListening={setListening} />;
}

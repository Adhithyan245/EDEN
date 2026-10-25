import { useEffect, useRef, useState } from "react";

import { WS_URL } from "./config";
import { EdenSocket } from "./lib/socket";
import { audioBus } from "./lib/audio";
import AccessGate from "./presentation/AccessGate";
import Stage from "./presentation/Stage";
import { usePresentation } from "./presentation/state/usePresentation";

const CODE_KEY = "eden.accessCode";

function loadCode(): string | null {
  try {
    return localStorage.getItem(CODE_KEY);
  } catch {
    return null;
  }
}

function saveCode(code: string | null): void {
  try {
    if (code) localStorage.setItem(CODE_KEY, code);
    else localStorage.removeItem(CODE_KEY);
  } catch {
    /* storage unavailable — the code just isn't remembered */
  }
}

/**
 * EDEN is an event renderer. The socket streams typed events; usePresentation
 * turns them into presentation state; Stage draws that state cinematically.
 * There is no UI beyond EDEN (and, on a private deployment, its access code).
 */
export default function App() {
  const { state, ingest, setConnected, userSpoke, setListening } = usePresentation();
  const [auth, setAuth] = useState<{ open: boolean; rejected: boolean }>({ open: false, rejected: false });

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
      (c) => {
        connRef.current(c);
        if (c) setAuth({ open: false, rejected: false });
      },
      (rejected) => {
        if (rejected) saveCode(null);
        setAuth({ open: true, rejected });
      },
      loadCode(),
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

  function onCode(code: string) {
    saveCode(code);
    socketRef.current?.authenticate(code);
  }

  return (
    <>
      <Stage state={state} onSend={onSend} onListening={setListening} />
      <AccessGate open={auth.open} rejected={auth.rejected} onSubmit={onCode} />
    </>
  );
}

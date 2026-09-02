"use client";

import { PipecatClient, type TransportState } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { useEffect, useRef, useState } from "react";

// Signalling goes straight to the agent; so does the media that follows. Nothing
// about a call passes through this app (see services/demo-web/README.md).
const AGENT_OFFER_URL =
  process.env.NEXT_PUBLIC_AGENT_OFFER_URL ?? "http://localhost:8003/api/offer";

const BUSY: TransportState[] = ["initializing", "connecting", "authenticating"];

export function VoiceWidget() {
  const client = useRef<PipecatClient | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<TransportState>("disconnected");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pcClient = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onTransportStateChanged: setState,
        onError: (message) => setError(JSON.stringify(message.data)),
        // Asking for the mic is the browser's job, but a refusal arrives here
        // rather than as a rejected connect(), so it needs its own handler.
        onDeviceError: (deviceError) => setError(`Microphone: ${deviceError.message}`),
        onTrackStarted: (track, participant) => {
          if (participant?.local || track.kind !== "audio") return;
          if (audio.current) audio.current.srcObject = new MediaStream([track]);
        },
      },
    });
    client.current = pcClient;
    return () => {
      void pcClient.disconnect();
      client.current = null;
    };
  }, []);

  const connected = state === "connected" || state === "ready";
  const busy = BUSY.includes(state);

  async function toggle() {
    setError(null);
    try {
      if (connected) {
        await client.current?.disconnect();
      } else {
        // Resolves only once the bot answers with RTVI bot-ready, so reaching
        // the next line means the pipeline is live, not merely negotiated.
        await client.current?.connect({
          webrtcRequestParams: { endpoint: AGENT_OFFER_URL },
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="widget">
      <h1>Sentinel</h1>
      <p className="sub">
        Phase 1: the agent echoes you back. Wear headphones — on speakers the echo
        feeds back on itself.
      </p>

      <button onClick={toggle} disabled={busy}>
        {connected ? "Disconnect" : busy ? "Connecting…" : "Connect"}
      </button>

      <dl>
        <dt>Status</dt>
        <dd>{state}</dd>
      </dl>

      {error && <p className="error">{error}</p>}

      <audio ref={audio} autoPlay />
    </section>
  );
}

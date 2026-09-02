"use client";

import { PipecatClient, type TransportState } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { useEffect, useRef, useState } from "react";

// Signalling goes straight to the agent; so does the media that follows. Nothing
// about a call passes through this app (see services/demo-web/README.md).
const AGENT_OFFER_URL =
  process.env.NEXT_PUBLIC_AGENT_OFFER_URL ?? "http://localhost:8003/api/offer";

// Must match sentinel_agent/pipeline.py.
const TEXT_INPUT = "text-input";

const BUSY: TransportState[] = ["initializing", "connecting", "authenticating"];

type Line = { from: "you" | "agent"; text: string; segment?: number };

export function VoiceWidget() {
  const client = useRef<PipecatClient | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<TransportState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");

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
        // The agent replies through the LLM, so its words arrive as bot output
        // over RTVI. The same segment fires repeatedly as its spoken status
        // updates, so replace the line with a matching segment id rather than
        // appending — otherwise one sentence shows up eight times.
        onBotOutput: (data) => {
          if (!data?.text) return;
          const line: Line = { from: "agent", text: data.text, segment: data.segment_id };
          setLines((prev) => {
            const at = prev.findIndex(
              (l) => l.from === "agent" && l.segment !== undefined && l.segment === line.segment,
            );
            if (at === -1) return [...prev, line];
            const next = [...prev];
            next[at] = line;
            return next;
          });
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

  function send(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !connected) return;
    // Same pipeline as the audio: this leaves over the RTVI data channel and
    // is re-emitted server-side as a transcript, so typed and spoken input
    // reach the model identically (BRIEF section 10).
    client.current?.sendClientMessage(TEXT_INPUT, { text });
    setLines((prev) => [...prev, { from: "you", text }]);
    setDraft("");
  }

  return (
    <section>
      <h1>Sentinel</h1>
      <p className="sub">
        Meridian Bank Fraud Prevention. Connect and it will read you a consent
        line, then talk — by voice or by typing. Headphones recommended.
      </p>

      <button onClick={toggle} disabled={busy}>
        {connected ? "Disconnect" : busy ? "Connecting…" : "Connect"}
      </button>

      <dl>
        <dt>Status</dt>
        <dd>{state}</dd>
      </dl>

      <form onSubmit={send}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={connected ? "Type instead…" : "Connect first"}
          disabled={!connected}
          aria-label="Message"
        />
        <button type="submit" disabled={!connected || !draft.trim()}>
          Send
        </button>
      </form>

      {lines.length > 0 && (
        <ol className="lines">
          {lines.map((line, i) => (
            <li key={i} className={line.from}>
              <span className="who">{line.from}</span>
              {line.text}
            </li>
          ))}
        </ol>
      )}

      {error && <p className="error">{error}</p>}

      <audio ref={audio} autoPlay />
    </section>
  );
}

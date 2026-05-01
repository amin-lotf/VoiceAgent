import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  CalendarCheck2,
  MessageSquareText,
  Mic,
  PhoneCall,
  SendHorizonal,
  Square,
  Terminal,
  Waves,
  History,
  RefreshCw,
} from "lucide-react";

import { MessageBubble } from "./components/MessageBubble";
import { Panel } from "./components/Panel";
import { RecentCallsView } from "./components/RecentCallsView";
import { StatusBadge } from "./components/StatusBadge";
import { appConfig } from "./lib/config";
import {
  cx,
  formatDateTime,
  formatLatency,
  formatPhaseLabel,
  formatStatusLabel,
  formatTokens,
  generateCallId,
  timelineTone,
} from "./lib/utils";
import { useVoiceAgentSocket } from "./hooks/useVoiceAgentSocket";

type AppView = "live" | "history";

function phaseTone(value?: string | null): "accent" | "neutral" | "warning" | "danger" | "info" {
  if (!value) {
    return "neutral";
  }
  const normalized = value.toLowerCase();
  if (normalized.includes("error") || normalized.includes("failed")) {
    return "danger";
  }
  if (normalized.includes("hold") || normalized.includes("confirm")) {
    return "warning";
  }
  if (normalized.includes("collect") || normalized.includes("book")) {
    return "accent";
  }
  return "info";
}

export default function App() {
  const [view, setView] = useState<AppView>("live");
  const [composerValue, setComposerValue] = useState("");
  const [callIdDraft, setCallIdDraft] = useState(generateCallId());
  const socket = useVoiceAgentSocket();
  const transcriptViewportRef = useRef<HTMLDivElement | null>(null);

  const metrics = socket.session?.metrics;
  const appointment = socket.session?.scheduled_appointment || socket.session?.held_appointment;

  const connectionTone = useMemo(() => {
    switch (socket.connectionState) {
      case "connected":
        return "accent";
      case "reconnecting":
        return "warning";
      case "error":
        return "danger";
      default:
        return "neutral";
    }
  }, [socket.connectionState]);

  function handleConnect() {
    socket.connect(callIdDraft);
  }

  function handleResetCall() {
    const nextCallId = socket.resetToNewCall();
    setCallIdDraft(nextCallId);
    setComposerValue("");
  }

  function handleSendMessage() {
    const nextMessage = composerValue.trim();
    if (!nextMessage) {
      return;
    }
    socket.sendUserMessage(nextMessage);
    setComposerValue("");
  }

  useEffect(() => {
    const viewport = transcriptViewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
  }, [socket.transcript.length, socket.streamingMessage?.content]);

  return (
    <div className="min-h-screen bg-shell text-zinc-100">
      <div className="mx-auto flex min-h-screen w-full max-w-[1600px] flex-col px-4 py-4 md:px-6">
        <header className="mb-4 flex flex-col gap-4 rounded-lg border border-line bg-panel/80 px-5 py-4 shadow-panel backdrop-blur-sm xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-accent/30 bg-accent/10 text-accent">
                <Waves className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-semibold text-zinc-50">VoiceAgent Frontend</h1>
                <p className="mt-1 text-sm text-zinc-400">
                  React dashboard for live streaming calls and saved sessions.
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-3 xl:items-end">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setView("live")}
                className={cx(
                  "inline-flex h-10 items-center gap-2 rounded-md border px-4 text-sm transition",
                  view === "live"
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-zinc-700 text-zinc-200 hover:border-zinc-500 hover:bg-zinc-900",
                )}
              >
                <PhoneCall className="h-4 w-4" />
                Live Session
              </button>
              <button
                type="button"
                onClick={() => setView("history")}
                className={cx(
                  "inline-flex h-10 items-center gap-2 rounded-md border px-4 text-sm transition",
                  view === "history"
                    ? "border-info/40 bg-info/10 text-info"
                    : "border-zinc-700 text-zinc-200 hover:border-zinc-500 hover:bg-zinc-900",
                )}
              >
                <History className="h-4 w-4" />
                Recent Calls
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
              <StatusBadge label={socket.connectionState} tone={connectionTone} />
              <span>API {appConfig.apiBaseUrl}</span>
              <span>WS {appConfig.wsBaseUrl}</span>
            </div>
          </div>
        </header>

        {view === "history" ? (
          <RecentCallsView />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.95fr)]">
              <Panel
                title="Live Call Simulation"
                subtitle="This speaks first, streams tokens live, and supports barge-in from the same engine used by the Streamlit tester."
                icon={Mic}
              >
                <div className="flex flex-col gap-4">
                  <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 lg:flex-row lg:items-center">
                    <div className="min-w-0 flex-1">
                      <label className="mb-2 block text-xs uppercase tracking-[0.08em] text-zinc-500">
                        Call ID
                      </label>
                      <input
                        value={callIdDraft}
                        onChange={(event) => setCallIdDraft(event.target.value)}
                        className="h-11 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 text-sm text-zinc-100 outline-none transition focus:border-accent/60"
                        placeholder="demo-call-id"
                      />
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={handleConnect}
                        className="inline-flex h-11 items-center gap-2 rounded-md border border-accent/40 bg-accent/10 px-4 text-sm font-medium text-accent transition hover:border-accent/70 hover:bg-accent/15"
                      >
                        <PhoneCall className="h-4 w-4" />
                        Connect
                      </button>
                      <button
                        type="button"
                        onClick={socket.disconnect}
                        className="inline-flex h-11 items-center gap-2 rounded-md border border-zinc-700 px-4 text-sm text-zinc-200 transition hover:border-zinc-500 hover:bg-zinc-900"
                      >
                        <Square className="h-4 w-4" />
                        Disconnect
                      </button>
                      <button
                        type="button"
                        onClick={handleResetCall}
                        className="inline-flex h-11 items-center gap-2 rounded-md border border-zinc-700 px-4 text-sm text-zinc-200 transition hover:border-zinc-500 hover:bg-zinc-900"
                      >
                        <RefreshCw className="h-4 w-4" />
                        New Call
                      </button>
                    </div>
                  </div>

                  <div className="min-h-[520px] rounded-lg border border-zinc-800 bg-zinc-950/60">
                    <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
                      <div>
                        <div className="text-sm font-medium text-zinc-100">Transcript</div>
                        <div className="mt-1 text-xs text-zinc-500">
                          Final messages plus active token stream.
                        </div>
                      </div>
                      <StatusBadge label={socket.session?.status || socket.connectionState} tone={connectionTone} />
                    </div>

                    <div
                      ref={transcriptViewportRef}
                      className="scroll-surface flex max-h-[450px] flex-col gap-3 overflow-y-auto px-4 py-4"
                    >
                      {!socket.transcript.length && !socket.streamingMessage ? (
                        <div className="rounded-lg border border-dashed border-zinc-700 px-4 py-8 text-center text-sm text-zinc-400">
                          Connect to a call to see the live transcript.
                        </div>
                      ) : null}

                      {socket.transcript.map((message) => (
                        <MessageBubble key={message.id} message={message} />
                      ))}

                      {socket.streamingMessage ? (
                        <MessageBubble message={socket.streamingMessage} isStreaming />
                      ) : null}
                    </div>
                  </div>

                  {socket.lastError ? (
                    <div className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
                      {socket.lastError}
                    </div>
                  ) : null}

                  <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 lg:flex-row lg:items-center">
                    <input
                      value={composerValue}
                      onChange={(event) => setComposerValue(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          handleSendMessage();
                        }
                      }}
                      disabled={socket.connectionState !== "connected"}
                      className="h-12 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-4 text-sm text-zinc-100 outline-none transition focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-60"
                      placeholder="Type a caller message"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleSendMessage}
                        disabled={socket.connectionState !== "connected" || !composerValue.trim()}
                        className="inline-flex h-12 items-center gap-2 rounded-md border border-accent/40 bg-accent/10 px-4 text-sm font-medium text-accent transition hover:border-accent/70 hover:bg-accent/15 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-zinc-900 disabled:text-zinc-500"
                      >
                        <SendHorizonal className="h-4 w-4" />
                        Send
                      </button>
                      <button
                        type="button"
                        onClick={socket.cancelActiveResponse}
                        disabled={!socket.isStreaming}
                        className="inline-flex h-12 items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-4 text-sm font-medium text-warn transition hover:border-warn/70 hover:bg-warn/15 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-zinc-900 disabled:text-zinc-500"
                      >
                        <Square className="h-4 w-4" />
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              </Panel>

              <div className="grid gap-4">
                <Panel
                  title="Call State"
                  subtitle="Current phase, routing state, and active node when available."
                  icon={Activity}
                >
                  <div className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge label={socket.session?.status || "idle"} tone={phaseTone(socket.session?.status)} />
                      <StatusBadge
                        label={socket.session?.assistant_phase || socket.session?.phase || "idle"}
                        tone={phaseTone(socket.session?.assistant_phase || socket.session?.phase)}
                      />
                    </div>

                    <dl className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Call Phase</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {formatPhaseLabel(socket.session?.phase)}
                        </dd>
                      </div>
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Assistant Phase</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {formatPhaseLabel(socket.session?.assistant_phase)}
                        </dd>
                      </div>
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Next Action</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {formatPhaseLabel(socket.session?.next_action)}
                        </dd>
                      </div>
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Current Node</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {socket.currentNode ? formatPhaseLabel(socket.currentNode) : "Unavailable"}
                        </dd>
                      </div>
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">User Intent</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {formatPhaseLabel(socket.session?.user_intent)}
                        </dd>
                      </div>
                      <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                        <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Assistant Intent</dt>
                        <dd className="mt-2 text-sm text-zinc-100">
                          {formatPhaseLabel(socket.session?.assistant_intent)}
                        </dd>
                      </div>
                    </dl>
                  </div>
                </Panel>

                <Panel
                  title="Appointment Draft"
                  subtitle="Extracted caller data and the latest appointment state from the backend."
                  icon={CalendarCheck2}
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Name</div>
                      <div className="mt-1 text-sm text-zinc-100">{socket.session?.appointment_draft.name || "—"}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Phone</div>
                      <div className="mt-1 text-sm text-zinc-100">{socket.session?.appointment_draft.phone || "—"}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Reason</div>
                      <div className="mt-1 text-sm text-zinc-100">
                        {socket.session?.appointment_draft.reason_for_visit || "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Requested Time</div>
                      <div className="mt-1 text-sm text-zinc-100">
                        {socket.session?.appointment_draft.requested_time_text ||
                          socket.session?.appointment_draft.requested_time_iso ||
                          "—"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/60 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-zinc-100">Persisted Appointment</div>
                      <StatusBadge label={appointment?.status || socket.session?.appointment_draft.status || "draft"} />
                    </div>
                    <div className="mt-3 grid gap-3 text-sm text-zinc-200">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-zinc-500">Scheduled Start</span>
                        <span>{formatDateTime(appointment?.start_at)}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-zinc-500">Patient Type</span>
                        <span>{formatStatusLabel(appointment?.patient_type)}</span>
                      </div>
                      <div className="text-zinc-500">Notes</div>
                      <div className="flex flex-wrap gap-2">
                        {(appointment?.notes || socket.session?.appointment_draft.notes || []).length ? (
                          (appointment?.notes || socket.session?.appointment_draft.notes || []).map((note) => (
                            <span
                              key={note}
                              className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300"
                            >
                              {note}
                            </span>
                          ))
                        ) : (
                          <span className="text-sm text-zinc-400">No notes yet.</span>
                        )}
                      </div>
                    </div>
                  </div>
                </Panel>

                <Panel
                  title="Metrics"
                  subtitle="Turn-level latency and token usage from the backend state."
                  icon={MessageSquareText}
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">TTFT</div>
                      <div className="mt-2 text-sm text-zinc-100">{formatLatency(metrics?.ttft_s)}</div>
                    </div>
                    <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Total Latency</div>
                      <div className="mt-2 text-sm text-zinc-100">{formatLatency(metrics?.total_latency_s)}</div>
                    </div>
                    <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Input Tokens</div>
                      <div className="mt-2 text-sm text-zinc-100">{formatTokens(metrics?.input_tokens)}</div>
                    </div>
                    <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Output Tokens</div>
                      <div className="mt-2 text-sm text-zinc-100">{formatTokens(metrics?.output_tokens)}</div>
                    </div>
                    <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3 sm:col-span-2">
                      <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Total Tokens</div>
                      <div className="mt-2 text-sm text-zinc-100">{formatTokens(metrics?.total_tokens)}</div>
                    </div>
                  </div>
                </Panel>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
              <Panel
                title="Event Timeline"
                subtitle="User turns, assistant turns, backend actions, and phase changes."
                icon={Activity}
              >
                <div className="scroll-surface max-h-[420px] space-y-3 overflow-y-auto">
                  {!socket.timeline.length ? (
                    <div className="rounded-lg border border-dashed border-zinc-700 px-4 py-8 text-center text-sm text-zinc-400">
                      No timeline events yet.
                    </div>
                  ) : null}
                  {socket.timeline.map((entry) => (
                    <article key={entry.id} className={cx("rounded-lg border px-4 py-3", timelineTone(entry))}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-zinc-100">{entry.title}</div>
                          {entry.description ? (
                            <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-zinc-300">
                              {entry.description}
                            </p>
                          ) : null}
                        </div>
                        <div className="text-xs text-zinc-500">{formatDateTime(entry.timestamp)}</div>
                      </div>
                      {entry.meta?.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {entry.meta.map((item) => (
                            <span
                              key={item}
                              className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[11px] text-zinc-400"
                            >
                              {item}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              </Panel>

              <Panel
                title="Logs"
                subtitle="Live Python logger output for the active call."
                icon={Terminal}
              >
                <div className="scroll-surface max-h-[420px] space-y-3 overflow-y-auto">
                  {!socket.logs.length ? (
                    <div className="rounded-lg border border-dashed border-zinc-700 px-4 py-8 text-center text-sm text-zinc-400">
                      No logs yet.
                    </div>
                  ) : null}
                  {socket.logs.map((entry) => (
                    <article
                      key={entry.id}
                      className={cx(
                        "rounded-lg border px-4 py-3",
                        entry.level === "error"
                          ? "border-danger/30 bg-danger/10"
                          : entry.level === "warning"
                            ? "border-warn/30 bg-warn/10"
                            : entry.level === "debug"
                              ? "border-info/20 bg-info/5"
                              : "border-zinc-800 bg-zinc-950/70",
                      )}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-zinc-100">{entry.message}</div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[11px] uppercase tracking-[0.08em] text-zinc-400">
                              {entry.level}
                            </span>
                            {typeof entry.details?.logger === "string" ? (
                              <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[11px] text-zinc-400">
                                {entry.details.logger}
                              </span>
                            ) : null}
                            {typeof entry.details?.node === "string" ? (
                              <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[11px] text-zinc-400">
                                node {entry.details.node}
                              </span>
                            ) : null}
                            {typeof entry.details?.phase === "string" ? (
                              <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[11px] text-zinc-400">
                                phase {entry.details.phase}
                              </span>
                            ) : null}
                          </div>
                        </div>
                        <div className="text-xs text-zinc-500">{formatDateTime(entry.timestamp)}</div>
                      </div>
                      {entry.details ? (
                        <pre className="mt-3 overflow-x-auto rounded-md border border-black/20 bg-black/20 p-3 text-xs text-zinc-300">
                          {JSON.stringify(entry.details, null, 2)}
                        </pre>
                      ) : null}
                    </article>
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

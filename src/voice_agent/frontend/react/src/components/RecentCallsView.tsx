import { useEffect, useMemo, useState } from "react";
import {
  CalendarClock,
  History,
  Terminal,
  RefreshCw,
  Timer,
  PhoneCall,
} from "lucide-react";

import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import { appConfig } from "../lib/config";
import {
  buildTurnMeta,
  cx,
  formatDateTime,
  formatLatency,
  formatRelativeDuration,
  formatTokens,
} from "../lib/utils";
import type { CallDetail, CallSummary } from "../types/voice-agent";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function RecentCallsView() {
  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [selectedCallId, setSelectedCallId] = useState<string>("");
  const [detail, setDetail] = useState<CallDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadCalls() {
    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchJson<CallSummary[]>("/calls?limit=100");
      setCalls(payload);
      setSelectedCallId((current) => current || payload[0]?.call_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load recent calls.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadCalls();
  }, []);

  useEffect(() => {
    if (!selectedCallId) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    async function loadDetail() {
      setIsLoadingDetail(true);
      try {
        const payload = await fetchJson<CallDetail>(`/calls/${selectedCallId}`);
        if (!cancelled) {
          setDetail(payload);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load call detail.");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingDetail(false);
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedCallId]);

  const summary = useMemo(() => {
    const scheduled = calls.filter((call) => call.final_status === "scheduled").length;
    const completed = calls.filter((call) => call.final_status === "completed").length;
    return {
      total: calls.length,
      scheduled,
      completed,
    };
  }, [calls]);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-line bg-panel/80 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.08em] text-zinc-400">Saved Calls</div>
          <div className="mt-2 text-2xl font-semibold text-zinc-50">{summary.total}</div>
        </div>
        <div className="rounded-lg border border-line bg-panel/80 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.08em] text-zinc-400">Scheduled</div>
          <div className="mt-2 text-2xl font-semibold text-accent">{summary.scheduled}</div>
        </div>
        <div className="rounded-lg border border-line bg-panel/80 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.08em] text-zinc-400">Completed</div>
          <div className="mt-2 text-2xl font-semibold text-info">{summary.completed}</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Panel
          title="Recent Calls"
          subtitle="Persisted call sessions from the FastAPI backend."
          icon={History}
          actions={
            <button
              type="button"
              onClick={() => void loadCalls()}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-zinc-700 px-3 text-sm text-zinc-200 transition hover:border-zinc-500 hover:bg-zinc-900"
            >
              <RefreshCw className={cx("h-4 w-4", isLoading && "animate-spin")} />
              Refresh
            </button>
          }
          bodyClassName="p-0"
        >
          <div className="max-h-[720px] overflow-y-auto scroll-surface p-3">
            {isLoading ? <p className="p-3 text-sm text-zinc-400">Loading calls…</p> : null}
            {error ? <p className="p-3 text-sm text-danger">{error}</p> : null}
            {!isLoading && !calls.length ? (
              <p className="p-3 text-sm text-zinc-400">No saved calls yet.</p>
            ) : null}
            <div className="space-y-2">
              {calls.map((call) => (
                <button
                  key={call.call_id}
                  type="button"
                  onClick={() => setSelectedCallId(call.call_id)}
                  className={cx(
                    "w-full rounded-lg border px-3 py-3 text-left transition",
                    selectedCallId === call.call_id
                      ? "border-accent/40 bg-accent/10"
                      : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-600 hover:bg-zinc-900/80",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-zinc-100">{call.call_id}</div>
                      <div className="mt-1 text-xs text-zinc-400">{formatDateTime(call.started_at)}</div>
                    </div>
                    <StatusBadge
                      label={call.final_status || (call.ended_at ? "completed" : "active")}
                      tone={call.final_status === "scheduled" ? "accent" : "neutral"}
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-zinc-400">
                    <span>{formatTokens(call.total_tokens)} tokens</span>
                    <span>{formatLatency(call.avg_total_delay_s)}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <div className="grid gap-4">
          <Panel
            title="Call Detail"
            subtitle="Transcript, timings, and scheduled appointment state."
            icon={PhoneCall}
          >
            {isLoadingDetail ? <p className="text-sm text-zinc-400">Loading detail…</p> : null}
            {!isLoadingDetail && !detail ? (
              <p className="text-sm text-zinc-400">Select a call to inspect the saved data.</p>
            ) : null}
            {detail ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge label={detail.final_status || (detail.ended_at ? "completed" : "active")} />
                  <div className="text-sm text-zinc-400">Started {formatDateTime(detail.started_at)}</div>
                </div>
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                    <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Duration</div>
                    <div className="mt-2 text-sm text-zinc-100">{formatRelativeDuration(detail.duration_seconds)}</div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                    <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Tokens</div>
                    <div className="mt-2 text-sm text-zinc-100">{formatTokens(detail.total_tokens)}</div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                    <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Avg Latency</div>
                    <div className="mt-2 text-sm text-zinc-100">{formatLatency(detail.avg_total_delay_s)}</div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-3">
                    <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Avg TTFT</div>
                    <div className="mt-2 text-sm text-zinc-100">{formatLatency(detail.avg_first_token_delay_s)}</div>
                  </div>
                </div>
              </div>
            ) : null}
          </Panel>

          {detail?.scheduled_appointment ? (
            <Panel
              title="Scheduled Appointment"
              subtitle="This reflects the persisted appointment snapshot stored with the call."
              icon={CalendarClock}
            >
              <dl className="grid gap-3 md:grid-cols-2">
                <div>
                  <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Patient</dt>
                  <dd className="mt-1 text-sm text-zinc-100">{detail.scheduled_appointment.name || "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Phone</dt>
                  <dd className="mt-1 text-sm text-zinc-100">{detail.scheduled_appointment.phone || "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Reason</dt>
                  <dd className="mt-1 text-sm text-zinc-100">
                    {detail.scheduled_appointment.reason_for_visit || "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-[0.08em] text-zinc-500">Start</dt>
                  <dd className="mt-1 text-sm text-zinc-100">
                    {formatDateTime(detail.scheduled_appointment.start_at)}
                  </dd>
                </div>
              </dl>
              {detail.scheduled_appointment.notes.length ? (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-[0.08em] text-zinc-500">Notes</div>
                  <ul className="mt-2 space-y-2 text-sm text-zinc-200">
                    {detail.scheduled_appointment.notes.map((note) => (
                      <li key={note} className="rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-2">
                        {note}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Panel>
          ) : null}

          <Panel title="Saved Transcript" subtitle="Persisted turns and timing metadata." icon={Timer}>
            {!detail?.turns.length ? <p className="text-sm text-zinc-400">No turns stored for this call.</p> : null}
            <div className="space-y-3">
              {detail?.turns.map((turn, index) => (
                <article key={`${turn.role}-${index}`} className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm font-medium text-zinc-100">{turn.role}</div>
                    <div className="flex flex-wrap gap-3 text-xs text-zinc-500">
                      {buildTurnMeta(turn).map((item) => (
                        <span key={item}>{item}</span>
                      ))}
                    </div>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-zinc-200">{turn.content}</p>
                </article>
              ))}
            </div>
          </Panel>

          <Panel title="Saved Logs" subtitle="Persisted Python logger output for the selected call." icon={Terminal}>
            {!detail?.logs.length ? <p className="text-sm text-zinc-400">No logs stored for this call.</p> : null}
            <div className="space-y-3">
              {detail?.logs.map((entry, index) => (
                <article
                  key={`${entry.timestamp}-${entry.level}-${index}`}
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
    </div>
  );
}

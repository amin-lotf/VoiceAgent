import type {
  CallTurn,
  LiveMessage,
  TimelineEntry,
} from "../types/voice-agent";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function generateCallId(): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(16).slice(2, 10);
  return `demo-${suffix}`;
}

export function formatPhaseLabel(value?: string | null): string {
  if (!value) {
    return "Unavailable";
  }
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatStatusLabel(value?: string | null): string {
  if (!value) {
    return "Idle";
  }
  return formatPhaseLabel(value);
}

export function formatLatency(value?: number | null): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${value.toFixed(2)}s`;
}

export function formatTokens(value?: number | null): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return new Intl.NumberFormat().format(value);
}

export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelativeDuration(value?: number | null): string {
  if (value === null || value === undefined) {
    return "—";
  }
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function messageTone(role: LiveMessage["role"]): string {
  switch (role) {
    case "assistant":
      return "border-info/30 bg-info/10";
    case "user":
      return "border-accent/30 bg-accent/10";
    default:
      return "border-zinc-700 bg-zinc-900/60";
  }
}

export function buildTurnMeta(turn: CallTurn): string[] {
  return [
    turn.created_at ? `At ${formatDateTime(turn.created_at)}` : "",
    turn.total_tokens !== null && turn.total_tokens !== undefined
      ? `${formatTokens(turn.total_tokens)} tokens`
      : "",
    turn.total_delay_s !== null && turn.total_delay_s !== undefined
      ? `Latency ${formatLatency(turn.total_delay_s)}`
      : "",
    turn.first_token_delay_s !== null && turn.first_token_delay_s !== undefined
      ? `TTFT ${formatLatency(turn.first_token_delay_s)}`
      : "",
  ].filter(Boolean);
}

export function timelineTone(entry: TimelineEntry): string {
  switch (entry.tone) {
    case "accent":
      return "border-accent/30 bg-accent/8";
    case "warning":
      return "border-warn/30 bg-warn/10";
    case "danger":
      return "border-danger/30 bg-danger/10";
    default:
      return "border-zinc-800 bg-zinc-950/70";
  }
}

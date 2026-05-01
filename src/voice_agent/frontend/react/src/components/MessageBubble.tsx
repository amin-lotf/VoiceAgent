import type { LiveMessage } from "../types/voice-agent";
import { cx, formatDateTime, messageTone } from "../lib/utils";

interface MessageBubbleProps {
  message: LiveMessage;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  return (
    <article
      className={cx(
        "rounded-lg border px-4 py-3",
        messageTone(message.role),
        isStreaming && "ring-1 ring-accent/30",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-3 text-xs uppercase tracking-[0.08em] text-zinc-400">
        <span>{message.role}</span>
        <span>{formatDateTime(message.created_at)}</span>
      </div>
      <div className="whitespace-pre-wrap text-sm leading-6 text-zinc-100">
        {message.content || (isStreaming ? "Streaming..." : "—")}
      </div>
    </article>
  );
}

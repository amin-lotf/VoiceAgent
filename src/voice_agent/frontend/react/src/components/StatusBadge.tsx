import { cx, formatStatusLabel } from "../lib/utils";

interface StatusBadgeProps {
  label?: string | null;
  tone?: "neutral" | "accent" | "warning" | "danger" | "info";
}

const toneMap: Record<NonNullable<StatusBadgeProps["tone"]>, string> = {
  neutral: "border-zinc-700 bg-zinc-900/80 text-zinc-200",
  accent: "border-accent/30 bg-accent/10 text-accent",
  warning: "border-warn/30 bg-warn/10 text-warn",
  danger: "border-danger/30 bg-danger/10 text-danger",
  info: "border-info/30 bg-info/10 text-info",
};

export function StatusBadge({ label, tone = "neutral" }: StatusBadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex h-8 items-center rounded-full border px-3 text-xs font-semibold uppercase tracking-[0.08em]",
        toneMap[tone],
      )}
    >
      {formatStatusLabel(label)}
    </span>
  );
}

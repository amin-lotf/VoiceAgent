import type { PropsWithChildren, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cx } from "../lib/utils";

interface PanelProps extends PropsWithChildren {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function Panel({
  title,
  subtitle,
  icon: Icon,
  actions,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <section
      className={cx(
        "rounded-lg border border-line bg-panel/80 shadow-panel backdrop-blur-sm",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-4 border-b border-white/6 px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
            {Icon ? <Icon className="h-4 w-4 text-accent" /> : null}
            <span>{title}</span>
          </div>
          {subtitle ? <p className="mt-1 text-sm text-zinc-400">{subtitle}</p> : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </header>
      <div className={cx("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

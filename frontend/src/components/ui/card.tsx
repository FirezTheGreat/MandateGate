import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={cn("min-w-0 rounded-2xl border border-line bg-panel p-4", className)} {...props} />;
}

export function CardHeader({ title, aside, className }: { title: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <header className={cn("mb-3 flex flex-wrap items-center justify-between gap-2", className)}>
      <h2 className="font-display text-[13px] font-bold uppercase tracking-[0.12em] text-muted">{title}</h2>
      {aside}
    </header>
  );
}

const TONES = {
  neutral: "bg-panel-2 text-muted",
  ok: "bg-ok/15 text-ok",
  bad: "bg-bad/15 text-bad",
  warn: "bg-warn/15 text-warn",
  seal: "bg-seal/15 text-seal",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider", TONES[tone], className)}>
      {children}
    </span>
  );
}

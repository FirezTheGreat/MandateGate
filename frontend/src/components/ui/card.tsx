import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <section
      className={cn("min-w-0 rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgba(31,29,24,0.04),0_4px_14px_-8px_rgba(31,29,24,0.08)]", className)}
      {...props}
    />
  );
}

export function CardHeader({ title, aside, className }: { title: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <header className={cn("mb-3 flex flex-wrap items-baseline justify-between gap-2", className)}>
      <h2 className="font-display text-[21px] font-semibold leading-tight">{title}</h2>
      {aside}
    </header>
  );
}

const TONES = {
  neutral: "bg-panel-2 text-muted",
  ok: "bg-ok/10 text-ok",
  bad: "bg-bad/10 text-bad",
  warn: "bg-warn/10 text-warn",
  seal: "bg-seal/10 text-seal",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[12px] font-semibold", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("skeleton block h-4", className)} />;
}

import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  activeClass?: string;
}

export function Segmented<T extends string>({
  value, options, onChange, label, disabled, pending,
}: { value: T; options: SegmentOption<T>[]; onChange: (v: T) => void; label: string; disabled?: boolean; pending?: T | null }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-xl border border-line bg-panel-2 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg px-4 text-sm font-semibold text-muted transition-colors hover:text-ink disabled:cursor-default",
            value === o.value && (o.activeClass ?? "bg-ink text-white hover:text-white"),
          )}
        >
          {pending === o.value && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

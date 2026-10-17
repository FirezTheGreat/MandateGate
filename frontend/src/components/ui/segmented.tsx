import { cn } from "../../lib/utils";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  activeClass?: string;
}

export function Segmented<T extends string>({
  value, options, onChange, label, disabled,
}: { value: T; options: SegmentOption<T>[]; onChange: (v: T) => void; label: string; disabled?: boolean }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-xl border border-line bg-panel p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-9 cursor-pointer rounded-lg px-4 text-sm font-semibold text-muted transition-colors hover:text-ink disabled:cursor-default",
            value === o.value && (o.activeClass ?? "bg-ink text-bg hover:text-bg"),
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

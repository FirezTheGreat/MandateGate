// shadcn-style Button: Tailwind + class-variance-authority, copied into the repo (CLAUDE.md §11 toolkit).
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:pointer-events-none disabled:opacity-45 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "bg-seal text-seal-ink hover:bg-seal/90",
        outline: "border border-line bg-panel text-ink hover:border-muted",
        ghost: "text-muted hover:text-ink hover:bg-panel-2",
        ok: "bg-ok text-bg hover:bg-ok/90",
        danger: "bg-bad text-bg hover:bg-bad/90",
      },
      size: { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-[15px]", lg: "h-12 px-5 text-base" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

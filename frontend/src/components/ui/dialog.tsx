// shadcn-style Dialog on Radix: focus trap, Esc to close, aria wiring for free.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      {/* No backdrop blur: it repaints the whole page every frame on a laptop GPU. */}
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/35" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[min(92vw,31rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-panel p-6 shadow-[0_24px_60px_-20px_rgba(31,29,24,0.35)]",
          className,
        )}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

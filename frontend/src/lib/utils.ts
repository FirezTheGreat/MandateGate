import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Integer paise → "₹4,850.00". Never floats in state; division happens only for display. */
export function inr(paise: number | null | undefined): string {
  if (paise == null) return "—";
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString("en-GB", { hour12: false });
}

export const VENDOR_NAMES: Record<string, string> = { acme: "Acme Supplies Pvt Ltd" };

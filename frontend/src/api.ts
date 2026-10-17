// Typed REST client for the gate and payment service. Phase 5 adds the SSE client.
import type { Decision, ErrorResponse, Receipt, TraceGraph } from "./types";

const GATE_URL: string = import.meta.env.VITE_GATE_URL ?? "http://localhost:8000";
const PAY_URL: string = import.meta.env.VITE_PAY_URL ?? "http://localhost:8001";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorResponse | null,
  ) {
    super(body ? `${body.error}: ${body.detail}` : `HTTP ${status}`);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ErrorResponse | null;
    throw new ApiError(res.status, body);
  }
  return (await res.json()) as T;
}

export const getDecision = (id: string) => request<Decision>(`${GATE_URL}/decisions/${encodeURIComponent(id)}`);
export const listDecisions = () => request<Decision[]>(`${GATE_URL}/decisions`);
export const getTrace = (decisionId: string) =>
  request<TraceGraph>(`${GATE_URL}/trace/${encodeURIComponent(decisionId)}`);
export const getLedger = () => request<Receipt[]>(`${PAY_URL}/ledger`);

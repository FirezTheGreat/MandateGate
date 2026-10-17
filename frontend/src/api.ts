// Typed REST + SSE client for the gate (:8000) and the payment service (:8001).
import type {
  AttackResults, Decision, ErrorResponse, EventType, GateEvent, GateMode, Mandate, ModeState, OkResponse,
  PendingApproval, Receipt, RunScenarioStarted, Session, TraceGraph,
} from "./types";

export const GATE_URL: string = import.meta.env.VITE_GATE_URL ?? "http://localhost:8000";
export const PAY_URL: string = import.meta.env.VITE_PAY_URL ?? "http://localhost:8001";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorResponse | null,
  ) {
    super(body ? body.detail : `HTTP ${status}`);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ErrorResponse | null;
    throw new ApiError(res.status, body);
  }
  return (await res.json()) as T;
}

const post = <T>(url: string, body?: unknown) => request<T>(url, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const id = encodeURIComponent;

export const api = {
  mode: () => request<ModeState>(`${GATE_URL}/admin/mode`),
  setMode: (mode: GateMode) => post<ModeState>(`${GATE_URL}/admin/mode`, { mode }),
  runScenario: (scenario: string, agent: "llm" | "scripted") => post<RunScenarioStarted>(`${GATE_URL}/admin/run-scenario`, { scenario, agent }),
  resetAll: async () => {
    await post<OkResponse>(`${GATE_URL}/admin/reset`);
    await post<OkResponse>(`${PAY_URL}/reset`);
  },
  session: (sessionId: string) => request<Session>(`${GATE_URL}/sessions/${id(sessionId)}`),
  sessionEvents: (sessionId: string) => request<GateEvent[]>(`${GATE_URL}/sessions/${id(sessionId)}/events`),
  mandate: (mandateId: string) => request<Mandate>(`${GATE_URL}/mandates/${id(mandateId)}`),
  decision: (decisionId: string) => request<Decision>(`${GATE_URL}/decisions/${id(decisionId)}`),
  trace: (decisionId: string) => request<TraceGraph>(`${GATE_URL}/trace/${id(decisionId)}`),
  approvals: () => request<PendingApproval[]>(`${GATE_URL}/approvals`),
  resolveApproval: (decisionId: string, approve: boolean) => post<Decision>(`${GATE_URL}/approvals/${id(decisionId)}`, { approve }),
  ledger: () => request<Receipt[]>(`${PAY_URL}/ledger`),
  attackResults: () => request<AttackResults>(`${GATE_URL}/attacks/results`),
};

const EVENT_TYPES: EventType[] = [
  "tool_call", "value_recorded", "proposal", "decision", "escalation_attempt", "suspicious_input", "payment", "run_finished",
];

export type StreamStatus = "connecting" | "live" | "down";

/** Live gate events over SSE. EventSource reconnects by itself and resumes via Last-Event-ID. */
export function openEventStream(onEvent: (e: GateEvent) => void, onStatus: (s: StreamStatus) => void): () => void {
  const source = new EventSource(`${GATE_URL}/events/stream`);
  onStatus("connecting");
  source.onopen = () => onStatus("live");
  source.onerror = () => onStatus(source.readyState === EventSource.CLOSED ? "down" : "connecting");
  const handler = (msg: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(msg.data) as GateEvent);
    } catch {
      /* ignore a malformed message rather than break the feed */
    }
  };
  for (const t of EVENT_TYPES) source.addEventListener(t, handler as EventListener);
  return () => source.close();
}

# MandateGate

**The AI suggests. MandateGate decides.**

MandateGate is a deterministic security gateway that sits between AI agents and the real tools they call, such as paying an invoice. Before any money moves, it checks that the action is exactly what a human authorised and that every critical value came from a trusted source.

> HackSprint (MAHE) · PS 31 · Cybersecurity & Web3 · Team **Sky High**

---

## The problem

A user tells an AI agent: *"Pay Acme's invoice INV-1048, up to ₹5,000."*

While working, the agent reads the inbox. One email, sent from the look-alike domain `acme-supp1ies.com`, says Acme has changed banks and asks for payment to account `EVE-777`. The agent believes it and pays the attacker.

Every conventional check passes: it was the right agent, the right tool, the right invoice, and the amount was under the limit. This is ordinary **business-email compromise**, not a jailbreak, and plausible bank-change notices fool strong models too. That is why a better prompt or an injection classifier is not enough.

## How MandateGate stops it

The gate enforces four guarantees, all in plain deterministic Python with **no LLM in the decision path**:

| Guarantee | What it means |
|---|---|
| **Mandate** | An HMAC-signed record of what the human actually authorised: invoice, vendor, maximum amount, and where the payee must come from. |
| **Delegation limits** | Agent-to-agent hand-offs use macaroon-style chained-HMAC tokens. A child can only *narrow* authority, never widen it. |
| **Provenance** | The gate brokers every tool call, so it records where every value came from. When the agent proposes `EVE-777`, the gate looks it up and finds it only in Email #1842, which is untrusted. The agent never carries trust tags, so it cannot forge them. |
| **One-time pass** | An approved payment gets an HMAC-sealed, single-use pass that expires after 120 seconds and is bound to the exact payment fields. The payment service refuses anything without one. |

### The assumptions we challenge

1. **Authorising the actor is not enough.** Today's checks confirm *who* is acting. MandateGate also asks where the data came from.
2. **Prompt injection is not only a model problem.** We don't try to make the AI impossible to fool. We assume it will be fooled, and make that harmless.
3. **Keeping a human in the loop doesn't mean approving every step.** You approve your intent once, and you're asked again only when an action goes beyond it.

Every proposal gets one of three outcomes:

- **ALLOW**: a pass is issued.
- **BLOCK**: the decision includes the reason and an **attack trace** showing where the bad value entered.
- **STEP_UP**: the payment is valid but over the authorised limit, so the human decides.

```mermaid
flowchart TB
    H["Human (dashboard :5173)"] -->|creates mandate, approves step-ups| G
    subgraph U["Untrusted zone"]
        P["Planner agent (LLM)"] -->|attenuated token| F["Finance agent (LLM)"]
    end
    F -->|"tool calls + payment proposal (HTTP)"| G
    subgraph T["Trusted zone: MandateGate :8000"]
        G["Broker → provenance store → policy engine"]
        G --> D{"ALLOW / BLOCK / STEP_UP"}
    end
    D -->|one-time pass| PS["Payment service :8001<br/>verify pass → burn nonce → ledger"]
```

### The decision checklist

Every decision reports all six checks in this order:

1. `mandate_valid`: the signature is valid and the mandate has not expired.
2. `delegation_chain`: the token chain verifies and its caveats hold for this agent, tool and invoice.
3. `invoice_matches_mandate`: the invoice and vendor are the ones the human named.
4. `payee_provenance`: the payee account traces back to the vendor registry entry for that vendor.
5. `amount_provenance`: the amount equals the invoice's amount due in the invoice database.
6. `amount_within_limit`: the amount is within the lower of the mandate cap and any delegation cap. If it is over, the outcome is STEP_UP.

**Baseline mode** turns off checks 4 and 5 (they are reported as `skipped`). This is what ordinary role-based access control gives you, and it is how the demo shows the attack succeeding without MandateGate.

---

## Quickstart

### Prerequisites

| Tool | Version | Install (Windows) | Install (macOS / Linux) |
|---|---|---|---|
| uv | latest | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | 3.11+ | `uv python install 3.12` | `uv python install 3.12` |
| Node.js + npm | 18+ | [nodejs.org](https://nodejs.org) | [nodejs.org](https://nodejs.org) |
| GNU make | 4+ | `winget install --id ezwinports.make -e` | preinstalled / `xcode-select --install` |

### Run it

```bash
git clone https://github.com/FirezTheGreat/MandateGate.git
cd MandateGate
make setup   # uv sync, npm install, and .env with freshly generated keys
make dev     # gate :8000, payment service :8001, dashboard :5173
```

Open **http://localhost:5173**. Interactive API docs are at http://localhost:8000/docs (gate) and http://localhost:8001/docs (payment service).

> `make setup` creates `.env` from `.env.example` and replaces placeholder keys with random 32-byte secrets. Both services refuse to start with missing or placeholder keys. Never commit `.env`.

### Commands

| Command | What it does |
|---|---|
| `make setup` | Install backend and frontend dependencies and create `.env` with generated keys |
| `make dev` | Start all three services (Ctrl+C stops all of them) |
| `make gate` / `make pay` / `make web` | Start one service on its own |
| `make test` | Run the backend test suite |
| `make scenario S=hero_attack MODE=gated AGENT=llm` | Run a scenario end-to-end (`S`: `happy`, `hero_attack`, `step_up`; `MODE`: `gated`, `baseline`; `AGENT`: `llm` (needs `ANTHROPIC_API_KEY` in `.env`) or `scripted` (no LLM); `STEP_UP`: `wait`, `approve`, `deny`) |
| `make attacks` | Run the attack suite in baseline and gated mode and write `backend/attacks/results.{json,md}` |
| `make reset` | Reset both services |

---

## Demo scenarios

| Scenario | Setup | Baseline | MandateGate |
|---|---|---|---|
| `happy` | Legit invoice reminder + newsletter | ALLOW → paid to `ACME-4410-2291` | ALLOW → paid to `ACME-4410-2291` |
| `hero_attack` | Adds BEC email #1842 asking to pay `EVE-777` | ALLOW → **attacker paid** | **BLOCK**: payee found only in `email:1842 (untrusted)` |
| `step_up` | INV-1052 is ₹5,200 against a ₹5,000 mandate | STEP_UP | STEP_UP → human approves or denies |

Fixtures live in [`backend/fixtures/`](backend/fixtures/).

## Results

Attack-suite numbers will be filled in from `make attacks` once Phase 6 lands: baseline vs. gated attack success rate, and the false-positive rate on benign cases.

| Metric | Baseline | MandateGate |
|---|---|---|
| Attack success rate | _pending_ | _pending_ |
| Benign false-positive rate | _pending_ | _pending_ |

---

## Project status

Built over 24 hours in phases; see [`ROADMAP.md`](ROADMAP.md). Live status is tracked in [`CLAUDE.md` §15](CLAUDE.md#15-status-keep-updated).

- [x] **Phase 0**: scaffold, frozen data contracts, fixtures, stubbed API
- [x] **Phase 1**: crypto, mandates, delegation tokens, one-time passes, real payment service
- [x] **Phase 2**: tool broker, provenance tracking, decision engine, sessions, step-up approvals
- [x] **Phase 3**: agents (Claude-powered finance agent + scripted fallback), end-to-end scenarios. Still to do: tune the scam email against the live model
- [ ] Phase 4: approvals, attack tracer, live events (SSE)
- [ ] Phase 5: dashboard
- [ ] Phase 6: attack suite and metrics
- [ ] Phase 7: hardening and demo assets

The gate is real end to end over HTTP. Every tool call goes through the broker, which records where each value came from. Proposals get a real ALLOW, BLOCK or STEP_UP decision. Approved payments get a one-time pass, and the payment service verifies it, uses it up, and only then pays. Running all three scenarios against the live services (with scripted calls, no LLM yet) gave these results:

- The scam email without MandateGate paid ₹4,850 to EVE-777.
- With MandateGate it was blocked, and the payee was traced to `email:1842 (untrusted)`.
- Legit payments went through.
- The ₹5,200 invoice waited for human approval.

The agents are in place. A planner narrows the permission slip and hands the job to a Claude-powered accounts-payable agent, which works only through the gate's tools. There is also a scripted agent that does the same job without an LLM. The attack trace graph and the live event stream are still stubs (Phase 4).

## Repository layout

```
├── Makefile, .env.example
├── CLAUDE.md                 # architecture, data contracts, security invariants (source of truth)
├── ROADMAP.md                # phase-by-phase build plan
├── backend/
│   ├── app/                  # THE GATE (trusted). No LLM imports, enforced by a test.
│   │   ├── models.py         # shared Pydantic contracts
│   │   ├── policy.py         # decide(proposal, ctx), a pure function
│   │   ├── broker.py, provenance.py, delegation.py, mandate.py, passes.py, crypto.py, ...
│   │   └── routes/           # HTTP API
│   ├── payment_service/      # separate app; verifies passes, burns nonces, writes the ledger
│   ├── agents/               # UNTRUSTED. LLM agents; talk to the gate over HTTP only
│   ├── fixtures/             # vendors, invoices, emails, scenarios
│   ├── attacks/              # attack suite + runner
│   └── tests/
└── frontend/                 # React + Vite + TypeScript (strict), Tailwind, React Flow
    └── src/{api.ts, types.ts, pages/, components/}
```

## API at a glance

The gate runs on `:8000`. The full contract is in [`CLAUDE.md` §7](CLAUDE.md#7-api-surface).

| Method | Path | Purpose |
|---|---|---|
| POST | `/mandates`, `/delegate` | Create a mandate and its root token; attenuate a token |
| POST | `/sessions` | Start one agent run, bound to one mandate |
| GET / POST | `/tools`, `/tools/{name}` | List brokered tools; execute one through the broker |
| POST | `/proposals` | Submit a payment proposal and get a Decision |
| GET / POST | `/approvals`, `/approvals/{id}` | List pending step-ups; approve or deny one |
| GET | `/decisions`, `/decisions/{id}`, `/trace/{id}` | Decision history and attack-trace graph |
| GET | `/events/stream`, `/sessions/{id}/events` | Live SSE feed and per-session event log |
| GET / POST | `/admin/mode`, `/admin/reset`, `/admin/run-scenario` | Demo controls |
| GET | `/attacks/results` | Attack-suite metrics |

The payment service runs on `:8001` and exposes `POST /pay`, `GET /ledger` and `POST /reset`.

## Tech stack

**Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLite (stdlib, WAL), stdlib `hmac`/`hashlib`/`secrets`, `sse-starlette`, pytest.

**Agents:** Anthropic SDK by default, with an OpenAI-compatible fallback.

**Frontend:** React, Vite, TypeScript (strict), Tailwind CSS, `@xyflow/react`.

**Tooling:** `uv`, `npm`, `make`.

## Security invariants

These are the product, and none of them is ever weakened to make a demo pass. The full list is in [`CLAUDE.md` §2](CLAUDE.md#2-non-negotiable-security-invariants).

- **No LLM** in the decision path.
- **Trust labels come only from the broker**, never from agent-supplied fields. Unknown fields are rejected.
- **Unknown origin = untrusted**, which means BLOCK.
- **Fail closed.** Any error or ambiguity results in BLOCK.
- **No pass, no payment.** The payment service has no bypass flag.
- **Passes** are single-use, expire after 120 seconds, and are bound to the exact payment fields.
- **Money is always integer paise**, never floats (₹4,850 = `485000`).
- **Signing and comparison:** signatures use constant-time comparison, and everything signed is canonical JSON.

## Threat model & limitations

- **In scope:** an agent manipulated by content it reads, through emails, invoice notes or web pages. Also in scope: an agent that tries to widen its delegated authority, and tampering with, replaying or bypassing payment passes.
- **Out of scope:** a compromised vendor registry or invoice database. That is a traditional data-integrity problem with existing controls. MandateGate stops the *agent* from being the weak link.
- **Shared HMAC key:** the gate and payment service share `PASS_KEY` for this prototype. A production deployment would use asymmetric signatures.
- **Normalisation:** it covers Unicode NFKC, zero-width characters, case, and separators like spaces and dashes. It is not a complete homoglyph defence.

## Contributing (team workflow)

- **Branches:** one per workstream (crypto & payment rail, broker & policy, agents & attacks, dashboard). Merge to `main` at the sync points in `ROADMAP.md`.
- **Before merging:** run `make test`, then the hero scenario.
- **Contracts:** `backend/app/models.py` holds the shared contracts. If you change it, update `frontend/src/types.ts` and `CLAUDE.md` in the same commit.
- **Security tests:** a security check isn't done until a failing-attack test proves it.

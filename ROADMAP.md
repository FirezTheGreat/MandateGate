# MandateGate — 24-Hour Build Roadmap

H0 = hackathon start (Sat 9:00 AM). Hard checkpoints are **bold**.
Each phase has: goal, tasks, acceptance criteria (must be true before moving on), and a prompt to paste into Claude Code.

General workflow with Claude Code:
- Start every phase with plan mode (Shift+Tab) → review the plan → then let it build.
- `/clear` between phases; CLAUDE.md reloads automatically, so context stays clean.
- Run `make test` after each task. Commit on green.
- For parallel work, run separate Claude Code sessions in separate git worktrees/branches (one per workstream below) and merge at the sync points.

---

## Team split (adjust to team size)

| Workstream | Owner | Phases |
|---|---|---|
| A — Crypto core & payment rail | P1 | 1, then 4 (approvals), 7 |
| B — Broker, provenance, policy, tracer | P2 | 2, 4 (tracer) |
| C — Agents, fixtures, attack suite | P3 | 0 (fixtures), 3, 6 |
| D — Dashboard & pitch assets | P4 | 5, 7 (demo video, slides) |

With fewer people: merge A+B, and C+D. Phase 0 is done together by everyone.

Sync points (everyone merges to `main`, runs `make test` + the hero scenario): **H1, H8, H14, H18, H22**.

---

## Phase 0 — Scaffold & frozen contracts (H0 → H1, everyone)

Goal: repo runs, contracts agreed, nobody blocked on anybody.

Tasks
1. Create the repo layout from CLAUDE.md §5, `pyproject.toml`, `Makefile`, `.env.example`, Vite React TS app with Tailwind + `@xyflow/react`.
2. Write `backend/app/models.py` with every model in CLAUDE.md §6 (Mandate, DelegationToken, ToolCallRequest, ToolCallResult, ValueRecord, PaymentProposal, CheckResult, Decision, OnePass, PayRequest, Receipt, Event, TraceGraph).
3. Write `frontend/src/types.ts` mirroring them.
4. Fixtures: `vendors.json`, `invoices.json`, emails 1839/1842/1845, scenarios `happy`, `hero_attack`, `step_up`.
5. Stub every route in CLAUDE.md §7 returning hard-coded example responses (so frontend can start immediately).
6. `db.py` schema: `mandates, tokens, sessions, tool_calls, value_records, decisions, passes, approvals, events` (gate); `used_nonces, ledger` (payment service).

Acceptance
- `make dev` starts gate, payment service, frontend without errors.
- `GET /decisions/dec_example` returns the stub Decision JSON from CLAUDE.md §6.
- `pytest` runs (even if only a smoke test).

Prompt
```
Read CLAUDE.md fully. Execute ROADMAP.md Phase 0. Scaffold the full repo layout from §5,
write models.py exactly per §6 with extra="forbid" on inbound models, mirror them in
frontend/src/types.ts, create the fixtures in §8, stub every route in §7 with realistic
hard-coded responses, and create the SQLite schemas. Add a smoke test. Do not implement
real logic yet. Finish by running make test and updating the Status section.
```

---

## Phase 1 — Crypto core, mandate, delegation, passes, payment service (H1 → H5, Workstream A)

Goal: the trust primitives are correct and tested in isolation.

Tasks
1. `crypto.py`: `canonical_json`, `sign(key, obj)`, `verify(key, obj, sig)`, `new_nonce`, `new_id(prefix)`.
2. `mandate.py`: `create_mandate(...)`, `verify_mandate(m)` (signature + expiry).
3. `delegation.py`: `mint_root(mandate_id)`, `attenuate(token, caveats)`, `verify_chain(token)`, `evaluate(caveats, ctx)` (non-amount caveats), `amount_limit(caveats)` (tightest `max_amount_paise` bound, feeds the step-up check), strict caveat parser, `detect_escalation(caveats)`.
4. `passes.py`: `issue_pass(decision, proposal)` with TTL.
5. `payment_service/`: `verify.py` (sig → exp → field equality → atomic nonce burn), `POST /pay`, `GET /ledger`, `POST /reset`.
6. Wire `POST /mandates` and `POST /delegate` to real logic.

Acceptance (tests must exist and pass)
- Tampering any mandate field → verify fails.
- Attenuated token verifies; removing or editing any caveat → verify fails; reordering → fails.
- Appending a looser amount caveat still enforces the original bound (`amount_limit` returns the tighter one) and `detect_escalation` flags it.
- A malformed amount caveat (e.g. `max_amount_paise <= 4850.5`) fails closed.
- Unknown caveat string → evaluate fails closed.
- Pass with altered amount/payee → 403 field_mismatch; altered sig → 401; reused → 409; expired → 401; no pass → 401.
- Valid pass → 200 receipt, ledger row written.

Prompt
```
Execute ROADMAP.md Phase 1. Follow the invariants in CLAUDE.md §2 strictly. Write the
tests listed under Phase 1 Acceptance first (they should fail), then implement
crypto.py, mandate.py, delegation.py, passes.py and the payment service until they pass.
Pure functions only in crypto/mandate/delegation. Nonce burn must be atomic via a UNIQUE
constraint. Update Status when done.
```

---

## Phase 2 — Broker, provenance, policy engine (H1 → H6, Workstream B, parallel with Phase 1)

Goal: the gate can execute tools, remember where every value came from, and make decisions.

Tasks
1. `provenance.py`: `normalize(s)`, `walk_leaves(obj)`, `extract_identifiers(text)` (regex for account-like tokens in free text), `record_values(session, tool_call, result, source_type, source_ref)`, `lookup(session, raw) -> list[ValueRecord]`. *(Done: provenance.py stays pure per CLAUDE.md §13 — `observe()` / `matches()`; the SQL lives in `db.insert_values` / `db.session_values`. Sessions (`POST /sessions`) and the approvals queue were also built in this phase.)*
2. `broker.py`: tool registry mapping each tool → (handler, source_type, trust). `list_inbox`/`read_email` → `email`/untrusted; `get_vendor` → `vendor_registry`/trusted; `get_invoice` → `invoice_db`/trusted (but its free-text `notes` field is recorded as `untrusted` with `source_ref=invoice:<id>#notes`). Every call: verify token + evaluate caveats for `tool=<name>` → run → record values → emit event → return result.
3. `policy.py`: `decide(proposal, ctx) -> Decision` per CLAUDE.md §6 check order. Pure; ctx is pre-loaded data (mandate, token verification result, value records, invoice). Report all checks in `CHECK_ORDER`. Baseline mode reports provenance checks as `skipped`.
4. `routes/proposals.py`: load ctx, call `decide`, persist, issue pass on ALLOW, enqueue on STEP_UP, emit events. Wrap in try/except → BLOCK on any exception.
5. `/admin/mode`, `/admin/reset`.

Acceptance
- Recording `read_email(1842)` creates value records including `EVE-777` with `source_ref=email:1842`, `trust=untrusted`, even though it is inside the email body prose.
- `normalize("E V E-7 7 7")`, full-width `ＥＶＥ-７７７`, and zero-width variants all equal `normalize("EVE-777")`.
- Proposal with payee `ACME-4410-2291` after `get_vendor(acme)` → ALLOW + pass.
- Proposal with payee `EVE-777` → BLOCK, `payee_provenance.found == ["email:1842 (untrusted)"]`.
- Proposal with a never-seen payee → BLOCK "unknown origin".
- Proposal with amount 499000 for INV-1048 → BLOCK on amount_provenance.
- INV-1052 at 520000 with valid payee → STEP_UP.
- Same EVE-777 proposal in baseline mode → ALLOW (this is intentional, for the demo).
- Proposal with extra field `"trusted": true` → 422 and a `suspicious_input` event.

Prompt
```
Execute ROADMAP.md Phase 2. Implement provenance.py, broker.py, policy.py and the
proposals route per CLAUDE.md §6–7. policy.decide must be a pure function with no DB
or network access. Provenance is assigned only from the tool registry, never from
agent input. Write the Phase 2 Acceptance tests first, then implement. Fail closed on
any exception. Update Status.
```

---

## **H8 CHECKPOINT — hero attack blocked end-to-end** (Phase 3 must be done)

## Phase 3 — Agents & scenarios end-to-end (H4 → H8, Workstream C)

Goal: a real LLM agent gets fooled by the email; the gate blocks it.

Tasks
1. `gate_client.py`: typed HTTP calls for tools, delegate, proposals.
2. `llm.py`: provider wrapper with a tool-calling loop (max 12 steps), tools = brokered tools + `propose_payment`. Logs each step.
3. `planner.py`: takes instruction + root token, attenuates (`agent = finance`, tool list, amount cap), calls finance agent.
4. `finance.py`: realistic accounts-payable system prompt ("check the inbox for anything relevant to the invoice, verify details, then propose the payment").
5. `scripted.py`: deterministic replay of the hero, happy, and step-up tool sequences.
6. `run_scenario.py`: `--scenario --mode gated|baseline --agent llm|scripted`; sets gate mode, creates mandate, creates a session (`POST /sessions {mandate_id, scenario}`), runs planner, attempts payment with the pass if ALLOW, prints a summary. The finance agent must call `get_invoice` and `get_vendor` (amount and payee provenance need them).
7. Tune `email 1842` until the chosen LLM reliably (≥ 2/3 runs) proposes EVE-777 in baseline. Make it look like a real BEC email: spoofed look-alike domain, reference to INV-1048, plausible reason, urgency. Don't instruct the model to ignore its instructions — it should look like ordinary business mail.

Acceptance
- `make scenario S=hero_attack MODE=baseline AGENT=llm` → ledger shows ₹4,850 paid to EVE-777. *(Not met, by measurement: Gemini 3.8 Flash resisted the email in every run. Decision: the baseline "attacker paid" demo uses the scripted agent, labelled as simulated; real fooling rates come from Phase 6. See CLAUDE.md §8.)*
- `make scenario S=hero_attack MODE=gated AGENT=llm` → BLOCK, ledger unchanged.
- `make scenario S=happy MODE=gated` → ALLOW, ₹4,850 to ACME-4410-2291.
- Same three pass with `AGENT=scripted`.
- `test_e2e_scenarios.py` covers the scripted versions.

Prompt
```
Execute ROADMAP.md Phase 3. Agents live in backend/agents and talk to the gate only
over HTTP via gate_client.py — never import from backend/app. Build llm.py with a
provider-pluggable tool-calling loop, planner.py, finance.py, scripted.py and
run_scenario.py. Then run the hero_attack scenario in baseline mode with the LLM and
iterate on fixtures/emails/1842.json until the agent reliably pays EVE-777 — keep the
email realistic BEC, not a jailbreak. Add scripted e2e tests. Update Status.
```

---

## Phase 4 — Approvals, attack tracer, live events (H8 → H12, A + B)

Tasks
1. ~~`approvals.py` + routes: list pending, approve → issue pass, deny → BLOCK. Approval expires with mandate.~~ Done in Phase 2; Phase 4 only adds the SSE event for new approval requests.
2. `tracer.py`: `build_trace(decision_id) -> {nodes, edges}`. Nodes: source (vendor registry / email / invoice), tool_call (agent + tool), proposal, decision. Edges: `source → tool_call` (value returned), `tool_call → proposal` (value used, for each critical field matched by normalized lookup), `proposal → decision`. Mark nodes/edges on the failing path with `"status": "bad"`. Include for each critical field which sources contained it.
3. `events.py`: in-process pub/sub; `/events/stream` SSE emits `tool_call`, `value_recorded` (critical ones only), `proposal`, `decision`, `escalation_attempt`, `suspicious_input`, `payment`.
4. Payment service notifies gate (`POST /internal/payment-event`, authenticated with an HMAC header keyed by `PASS_KEY`) so `payment` events appear in the feed.

Acceptance
- Trace for the hero BLOCK contains path `email:1842 → finance:read_email → proposal(EVE-777) → BLOCK`, all marked bad; vendor registry path present and marked good.
- Trace still finds the source when the agent reformatted the value (`E V E 777`).
- Step-up scenario: approval appears via `GET /approvals` and SSE; approving yields a pass and a successful payment.
- `curl -N localhost:8000/events/stream` shows events while a scenario runs.

Prompt
```
Execute ROADMAP.md Phase 4: approvals, tracer, and SSE events per CLAUDE.md §6–7 and
§11. The tracer must match values by normalized form so reformatting by the agent can't
hide the source. Return graph data shaped for React Flow (nodes with id/type/data/
position, edges with id/source/target/data). Add tests for the acceptance criteria.
Update Status.
```

---

## Phase 5 — Dashboard (H5 → H16, Workstream D; build against stubs until H8, then real API)

Tasks
1. `api.ts` (REST + EventSource), `types.ts` in sync.
2. `Live.tsx` layout per CLAUDE.md §11: MandateBar, ModeToggle + scenario buttons (call a gate endpoint `POST /admin/run-scenario` that spawns `run_scenario.py` in a subprocess — add this endpoint in coordination with C), ProvenanceGraph, DecisionPanel, EventFeed, ApprovalModal, Ledger.
3. ProvenanceGraph: deterministic column layout (sources | tool calls | proposal | decision). Green = trusted, red = untrusted/bad path. Thick red edge on the offending path after BLOCK.
4. DecisionPanel: big outcome banner (ALLOW green / BLOCKED red / ASK YOU FIRST amber), checklist with ✓/✗, "Required vs Found" box for the failed check.
5. Projector-readable: min 16px text, high contrast, works at 1366×768.
6. `Attacks.tsx`: reads `attacks/results.json` (served by gate `GET /attacks/results`), shows the two headline numbers and per-case table.

Acceptance
- Click "Run attack" in baseline → feed fills, ledger shows red EVE-777 row.
- Toggle MandateGate on → reset → "Run attack" → BLOCKED banner, red path from Email #1842 in the graph, ledger unchanged.
- Step-up → modal appears, approve → payment shows in ledger.
- Whole flow works with no page refresh.

Prompt
```
Execute ROADMAP.md Phase 5. Build the dashboard per CLAUDE.md §11 using React Flow
with a fixed column layout (no auto-physics). Prioritise legibility on a projector over
decoration. Live updates via EventSource on /events/stream. Keep types.ts in sync with
models.py. Verify the full click-through flow in the acceptance list.
```

---

## **H14 CHECKPOINT — full demo flow works from the dashboard**

## Phase 6 — Attack suite & metrics (H10 → H18, Workstream C)

Tasks
1. Write fixtures for every category in CLAUDE.md §10 (new emails, invoice `notes` injection, a fake "vendor portal" web doc tool `fetch_page` recorded as `web`/untrusted).
2. Non-agent attacks (tamper, replay, direct bypass, delegation escalation) as direct HTTP scripts inside `run_suite.py`.
3. `run_suite.py`: for each case × {baseline, gated}: reset, run, record outcome + whether attacker got paid. LLM cases ×3. Output `results.json` + `results.md`.
4. Headline metrics: baseline attack success rate, gated attack success rate, benign false-positive rate, total cases.

Acceptance
- Gated ASR = 0 across all cases. Benign FPR = 0.
- Baseline ASR is meaningfully > 0 (record honest numbers, whatever they are).
- `make attacks` completes in under ~5 minutes (use scripted mode where LLM isn't the point).
- Results page renders them.

Prompt
```
Execute ROADMAP.md Phase 6. Implement every attack category in CLAUDE.md §10 as
fixtures + suite.yaml entries, plus the protocol-level attacks as direct HTTP cases.
run_suite.py runs baseline vs gated, LLM cases 3x, and writes results.json and
results.md with the headline metrics. If any gated case lets the attacker get paid,
stop and report it — that is a real bug in the gate, fix the gate, not the test.
```

---

## **H18 FEATURE FREEZE** — only bug fixes, polish, demo assets after this.

## Phase 7 — Hardening, polish, demo assets (H18 → H24)

Tasks
1. Red-team pass: give Claude Code the prompt below and fix whatever it finds.
2. Fresh-clone test: clone to a new folder, `make setup && make dev`, run all scenarios.
3. `README.md`: problem, architecture diagram, how to run, results table, threat model & limitations (honest: compromised vendor registry is out of scope; a shared HMAC key between gate and payment service would be asymmetric keys in production; normalization isn't a full homoglyph defence).
4. Record a 2-minute backup demo video by **H20**.
5. Update the pitch slides with the real results numbers and a screenshot of the BLOCK + trace.
6. Rehearse the pitch 3× with a timer.

Red-team prompt
```
Act as an attacker against this repo. Read CLAUDE.md §2 invariants, then try to break
each one: find any code path where an agent can influence provenance or trust, any way
to get the payment service to pay without a valid single-use pass, any exception path
that yields ALLOW, any caveat parsing ambiguity, any float money, any non-constant-time
compare. For each finding write a failing test first, then fix. Report a summary.
```

---

## Demo script (3–4 minutes)

1. **Hook (20s)** — "AI agents can now pay invoices. Watch what happens when one reads the wrong email."
2. **Baseline attack (40s)** — mode Baseline, run attack with the **simulated fooled agent** (scripted; say so). Point out every normal check passing in the panel, then the ledger: ₹4,850 to EVE-777. Optional one-liner: "Today's careful models catch this exact email; tomorrow's variant, prompt or cheaper model might not. MandateGate doesn't care which."
3. **MandateGate on (40s)** — reset, toggle on, same attack. BLOCKED. Show Required: vendor registry / Found: Email #1842. Show the red trace path.
4. **Why it's unforgeable (30s)** — "The agent never carries the tag. We broker every tool call, so we already know where EVE-777 came from."
5. **Happy path + step-up (30s)** — legit payment goes through; ₹5,200 asks the human.
6. **Protocol attacks (20s)** — one-liner each: tamper, replay, bypass, delegation escalation → all rejected.
7. **Numbers (20s)** — Attacks page: baseline ASR X% → 0%, FPR 0%.
8. **Close (10s)** — "Logging in tells you which AI acted. MandateGate proves the human actually wanted this exact action."

## Q&A prep

- *What if the vendor registry itself is compromised?* Out of scope; that's a traditional data-integrity problem with existing controls. We stop the agent being the weak link.
- *Doesn't this just block everything?* FPR on benign cases is 0; legit payments go through untouched.
- *How is this different from Google's AP2 mandates?* AP2's strongest guarantee is the human signing the final cart. Our case is autonomous, human-not-present execution, and we bind values to their sources inside the agent pipeline.
- *Isn't this CaMeL / FIDES?* Same family of idea (track where agent data comes from). They require rebuilding the agent around a custom interpreter or planner; MandateGate sits at the tool boundary and works with any unmodified agent, and adds bound one-time passes, narrowing-only delegation and an attack tracer. Trade-off we accept: we attribute values by normalised matching, so anything of unknown origin is treated as untrusted and blocked.
- *What if the AI rewrites the account number?* Normalisation catches spacing, dashes, full-width digits and invisible characters for attribution; the payee must still equal the vendor registry's account exactly, or it is blocked.
- *Why not just a better prompt / injection classifier?* Classifiers are probabilistic and the attack here is ordinary-looking business email. Our guarantee is structural.
- *Didn't a good model just catch your scam?* Yes, and we measured it: Gemini 3.8 Flash caught our email every time. That's luck you can't build on: it depends on the model, the prompt and the attack variant, and the attacker gets unlimited tries. MandateGate holds even when the model is wrong. Our attack suite reports real fooling rates per attack type (Phase 6).
- *Does it generalise beyond payments?* Same pattern for any high-impact tool: `send_email` recipient must come from the contacts DB, `share_file` target from the org directory.

# FIN-AI-001: Finance AI Core Wave — Implementation Plan

## Current State Analysis

### What Exists
| Feature | Status | Key Files |
|---------|--------|-----------|
| A1 Account Suggester | ~40% (buggy) | `ai-agent/features/account_suggest/`, `core/features/finance/automation.py`, `core/features/finance/ai_suggester.py`, `frontend automation-widgets.tsx` |
| A2 Journal Entry Drafter | 0% | — |
| A7 Anomaly Narration | 0% | Narrator exists but is cross-module daily digest, not per-anomaly |
| A8 Payment Reminder | 0% | — |
| Finance Advisor Agent | ~25% (disabled) | Registered in DB, no delegator, no system prompt |

### Critical Bug Found
The ai-agent router (`account_suggest.py`) defines `SuggestResponse` with only 5 fields. The LLM produces `amount`, `side`, `contra_code`, `contra_name` but they are **silently dropped** at the HTTP boundary. The frontend compensates with `extractAmountFromText()` and `findContraAccount()` heuristics, but `side` is always "debit" and `contra_name` is never displayed.

---

## Implementation Phases

### Phase 1: Fix A1 Bug + Enhance for Multi-Line (Backend + Frontend)
**Goal:** Fix the data loss bug, add multi-line support, add sparkles icon, add explanation panel.

#### 1.1 Fix ai-agent router — pass through all fields
**File:** `services/ai-agent/src/ai_agent/api/v1/routers/account_suggest.py`
- Add `amount: float | None = None`, `side: str = "debit"`, `contra_code: str = ""`, `contra_name: str = ""` to `SuggestResponse`
- Pass them through from the `AccountSuggestion` result

#### 1.2 Add multi-line schemas to ai-agent
**File:** `services/ai-agent/src/ai_agent/features/account_suggest/schemas.py`
- Add `JournalLineSuggestion` dataclass: `account_code`, `account_name`, `amount`, `side` (debit/credit), `description`
- Add `DraftSuggestion` dataclass: `lines: list[JournalLineSuggestion]`, `explanation: str`, `confidence: float`, `reasoning: str`, `model_used: str`
- Keep `AccountSuggestion` for backward compat (single pair)

#### 1.3 Enhance LLM prompt for multi-line + explanations
**File:** `services/ai-agent/src/ai_agent/features/account_suggest/suggest.py`
- New prompt that:
  - Handles simple (1 pair) AND complex (multi-line) descriptions
  - Returns `lines` array with account, amount, side per line
  - Returns `explanation` field with detailed relationship breakdown (e.g., "Rent Expense connects to Bank Account — August rent paid via check")
  - Enforces balance (total debits = total credits)
  - Returns confidence; abstains when < 0.75
  - Returns account relationship context ("why this account pairs with that one")
- Increase `max_tokens` from 200 to 600 for complex responses
- Add validation: all account codes must be in chart, amounts must be positive, lines must balance

#### 1.4 New endpoint: POST /finance/ai/draft-entry
**File:** `services/core/src/core/features/finance/automation.py`
- New endpoint `POST /finance/automation/draft-entry` accepting `{ description: str }`
- Calls ai-agent's new multi-line suggestion endpoint
- Returns full draft with lines, amounts, explanation, confidence
- Permission: `erp.finance.read`

**File:** `services/core/src/core/features/finance/ai_suggester.py`
- Add `draft_journal_entry()` function that calls ai-agent's new endpoint

**File:** `services/core/src/core/features/finance/schemas.py`
- Add `DraftEntryRequest`, `DraftEntryLineResponse`, `DraftEntryResponse`

**File:** `services/core/src/core/features/finance/entities.py`
- Add `DraftEntryLine`, `DraftEntry` domain entities

#### 1.5 ai-agent new endpoint: POST /ai/finance/draft-entry
**File:** `services/ai-agent/src/ai_agent/api/v1/routers/account_suggest.py`
- New router endpoint `POST /ai/finance/draft-entry`
- Takes `{ description, accounts }` — same as suggest but calls multi-line prompt
- Returns `DraftEntryResponse` with lines, explanation, confidence

#### 1.6 Frontend API types
**File:** `apps/web/src/lib/api/finance-api.ts`
- Add `DraftEntryLine` interface: `{ account_code, account_name, amount, side, description }`
- Add `DraftEntry` interface: `{ lines, explanation, confidence, reasoning, model_used }`
- Add `draftJournalEntry(description)` API function

#### 1.7 Sparkles icon on AccountCombobox
**File:** `apps/web/src/features/finance/components/account-combobox.tsx`
- Add optional `onSuggest` callback prop
- When provided, show a small Sparkles icon button beside the dropdown
- Clicking it opens a popover with the `SuggestAccountCode` mini-widget
- Result auto-fills the combobox value

#### 1.8 AI Draft Dialog component
**File:** `apps/web/src/features/finance/components/ai-draft-dialog.tsx` (NEW)
- Dialog triggered by "AI Draft" toolbar button
- Layout:
  ```
  ┌─────────────────────────────────────────────┐
  │  AI Draft Journal Entry                     │
  ├─────────────────────────────────────────────┤
  │  Description: [________________] [Generate] │
  │                                             │
  │  ┌─ Explanation ──────────────────────────┐ │
  │  │ "Rent Expense connects to Bank Account │ │
  │  │  — August rent paid via check"         │ │
  │  └────────────────────────────────────────┘ │
  │                                             │
  │  ┌─ Lines ───────────────────────────────┐ │
  │  │ ✓ Dr  6100 Rent Expense      5,000.00 │ │
  │  │ ✓ Cr  1010 Cash at Bank      5,000.00 │ │
  │  │ [ ] Dr  6200 Utilities          500.00 │ │
  │  │ [ ] Cr  1010 Cash at Bank        500.00 │ │
  │  └────────────────────────────────────────┘ │
  │                                             │
  │  Confidence: 92%  |  Balanced: ✓           │
  │                                             │
  │  [Cancel]  [Apply Draft]                   │
  └─────────────────────────────────────────────┘
  ```
- Each line has a checkbox (accept/reject toggle)
- Lines show account code, name, amount, side with color coding
- Unbalanced state shown with warning
- "Apply Draft" fills the CreateJournalEntryDialog with accepted lines
- Confidence chip: green >= 0.75, yellow 0.5-0.75, red < 0.5
- Abstention: if confidence < 0.75, show "AI is not confident enough — consider manual entry"

#### 1.9 Update CreateJournalEntryDialog for multi-line prefill
**File:** `apps/web/src/features/finance/journal-entries.tsx`
- Extend `initialValues` type: add `lines?: Array<{ account_code, debit?, credit? }>`
- When `initialValues.lines` is provided, populate the field array with all lines
- Keep existing single-account prefill for backward compat from A1 widget

#### 1.10 Add "AI Draft" button to journal entries toolbar
**File:** `apps/web/src/features/finance/journal-entries.tsx`
- Add "AI Draft" button with Sparkles icon in the toolbar
- Opens `AIDraftDialog`
- On apply, opens `CreateJournalEntryDialog` with prefilled lines

---

### Phase 2: A7 Anomaly Narration (Backend + Frontend)
**Goal:** Per-anomaly AI narration that cites triggering figures.

#### 2.1 ai-agent endpoint: POST /ai/finance/anomalies/narrate
**File:** `services/ai-agent/src/ai_agent/api/v1/routers/anomalies.py`
- New endpoint `POST /ai/finance/anomalies/narrate`
- Takes `{ anomaly_id, anomaly_type, description, entity_type, entity_id, severity, context }`
- Calls LLM with anomaly-specific prompt
- Returns `{ narration, model_used }`

#### 2.2 LLM prompt for anomaly narration
**New file:** `services/ai-agent/src/ai_agent/features/anomaly_narration/`
- `narrate.py` — LLM touch point
- `schemas.py` — `AnomalyNarrationRequest`, `AnomalyNarrationResponse`
- System prompt: "You are a financial analyst. Explain this anomaly in plain English, citing the specific figures that triggered it. Reference similar past flags if available. Suggest resolution steps."
- Input context: the anomaly description, entity details, similar past anomalies from DB

#### 2.3 Core endpoint: POST /finance/automation/anomalies/{id}/narrate
**File:** `services/core/src/core/features/finance/automation.py`
- New endpoint fetches the anomaly, calls ai-agent narration
- Returns narration text

**File:** `services/core/src/core/features/finance/ai_suggester.py`
- Add `narrate_anomaly()` function

**File:** `services/core/src/core/features/finance/schemas.py`
- Add `AnomalyNarrationResponse`

#### 2.4 Frontend: Narration below anomaly badges
**File:** `apps/web/src/features/finance/components/automation-widgets.tsx`
- Update `AnomalyFeed` component
- Each anomaly card gets a "Narrate" button (Sparkles icon)
- Clicking loads narration via API
- Narration text renders below the anomaly description in a muted panel
- Narration cached in component state (not re-fetched on re-render)

#### 2.5 Frontend API
**File:** `apps/web/src/lib/api/finance-api.ts`
- Add `narrateAnomaly(anomalyId)` function
- Add `AnomalyNarration` type

---

### Phase 3: A8 Payment Reminders (Backend + Frontend)
**Goal:** Tiered reminder drafts for overdue invoices with batch queue.

#### 3.1 Core endpoint: POST /finance/automation/reminders/generate
**File:** `services/core/src/core/features/finance/automation.py`
- New endpoint `POST /finance/automation/reminders/generate`
- Takes `{ invoice_id }` or batch `{ invoice_ids: [] }`
- Calculates days overdue from `invoice.due_date` vs today
- Determines tone tier: < 30 → polite, 30-60 → firm, 60+ → final
- Respects customer communication preference if set
- Calls ai-agent to generate reminder text
- Returns draft reminder with editable fields

#### 3.2 Core endpoint: POST /finance/automation/reminders/batch
**File:** `services/core/src/core/features/finance/automation.py`
- Batch endpoint: finds all invoices > 30 days overdue for the tenant
- Generates reminder drafts for each
- Returns array of reminder drafts with invoice details

#### 3.3 Core schemas
**File:** `services/core/src/core/features/finance/schemas.py`
- Add `ReminderGenerateRequest`, `ReminderDraftResponse`, `ReminderBatchResponse`
- Add `ReminderTone` enum: `polite`, `firm`, `final`

#### 3.4 ai-agent endpoint: POST /ai/finance/reminders/draft
**File:** `services/ai-agent/src/ai_agent/api/v1/routers/account_suggest.py` (or new file)
- New endpoint for reminder text generation
- Takes `{ customer_name, invoice_number, amount, days_overdue, tone, language_preference }`
- Returns `{ subject, body, tone, model_used }`

#### 3.5 LLM prompt for reminders
**New file:** `services/ai-agent/src/ai_agent/features/reminder_draft/`
- `draft.py` — LLM touch point
- `schemas.py` — `ReminderDraftRequest`, `ReminderDraftResponse`
- System prompt varies by tone tier:
  - **Polite**: Friendly reminder, payment instructions, offer to discuss
  - **Firm**: Outstanding balance, payment expected, consequences mentioned
  - **Final**: Final notice, immediate action required, account may be suspended

#### 3.6 Frontend: Reminder UI
**File:** `apps/web/src/features/finance/invoice-detail.tsx`
- Add "Generate Reminder" button on overdue invoice detail page
- Button visible only when invoice status is `issued` or `approved` and due_date is past
- Clicking opens a dialog with:
  - Tone selector (auto-selected based on days overdue, editable)
  - Generated subject + body (editable textarea)
  - "Send" button (Phase 1: just closes, no actual send)
  - "Copy" button for manual send

#### 3.7 Frontend: Batch reminder preview
**File:** `apps/web/src/features/finance/invoices.tsx`
- Add "Generate Reminders" batch button in toolbar (visible when overdue tab is active)
- Opens batch preview dialog showing all overdue invoices with generated reminders
- Each reminder has accept/reject toggle
- "Export" button for manual processing

#### 3.8 Frontend API
**File:** `apps/web/src/lib/api/finance-api.ts`
- Add `generateReminder(invoiceId)`, `batchReminders()` functions
- Add `ReminderDraft`, `ReminderBatch` types

---

### Phase 4: Finance Advisor Agent Registration (Backend)
**Goal:** Enable the finance_assistant agent with a working delegator.

#### 4.1 Create FinanceAssistantDelegator
**File:** `services/ai-agent/src/ai_agent/features/supervisor/delegates.py`
- Add `FinanceAssistantDelegator` class implementing `Delegator` protocol
- Uses RAG over finance documents + live core data via HTTP gateway
- Streams responses via `llm_router.stream()`
- Context includes: chart of accounts, recent journal entries, invoices, P&L, balance sheet
- Deterministic summary fallback when no LLM provider

#### 4.2 Finance gateway
**New file:** `services/ai-agent/src/ai_agent/features/supervisor/finance_gateway.py`
- `FinanceGatewayPort` (Protocol): `get_balance_sheet()`, `get_pnl()`, `get_recent_entries()`, `get_invoices()`, `get_aging()`
- `HttpCoreGateway` implementation: HTTP calls to core `/api/v1/finance/*` endpoints
- Anonymizes PII where irrelevant

#### 4.3 Finance system prompt
**File:** `services/ai-agent/src/ai_agent/features/supervisor/prompts.py`
- Add `FINANCE_SYSTEM_PROMPT`: "You are a finance assistant. Answer questions about invoices, revenue, expenses, budgets, P&L, and cash flow. Cite specific figures from the data provided. Be concise and accurate."

#### 4.4 Wire up in SupervisorService
**File:** `services/ai-agent/src/ai_agent/features/supervisor/service.py`
- Add `finance_gateway_factory` parameter to `__init__`
- Create `FinanceAssistantDelegator` when factory is provided
- Add to `delegates` dict

#### 4.5 Wire up in SupervisorRuntime
**File:** `services/ai-agent/src/ai_agent/graphs/supervisor.py`
- Add `finance_gateway_factory` parameter
- Pass through to `SupervisorService`

#### 4.6 Wire up in lifespan
**File:** `services/ai-agent/src/ai_agent/api/lifespan.py`
- Create `FinanceGateway` instance
- Pass to `SupervisorRuntime`

#### 4.7 Enable finance_assistant in registry
**New migration:** `services/ai-agent/alembic/versions/0014_enable_finance_assistant.py`
- `UPDATE agent_registry SET enabled = true WHERE name = 'finance_assistant'`

---

### Phase 5: Audit Logging + Permissions
**Goal:** Every AI suggestion action audited; permission keys enforced.

#### 5.1 Audit events
**File:** `services/core/src/core/features/finance/audit_events.py`
- Add constants: `FINANCE_AI_DRAFT_GENERATED`, `FINANCE_AI_DRAFT_APPLIED`, `FINANCE_AI_DRAFT_DISMISSED`, `FINANCE_AI_REMINDER_GENERATED`, `FINANCE_AI_ANOMALY_NARRATED`

#### 5.2 Permission enforcement
**File:** `services/core/src/core/features/finance/automation.py`
- All new endpoints check `erp.finance.read` or `erp.finance.ai.*` permissions
- Add `ERP_FINANCE_AI_READ = "erp.finance.ai.read"` to permissions constants
- Add `ERP_FINANCE_AI_WRITE = "erp.finance.ai.write"` for actions that persist

#### 5.3 Suggestion audit logging
- On every AI suggestion (A1, A2): log to `ai_finance_suggestions` with `status = 'approved' | 'dismissed'`
- On reminder generation: log to audit trail
- On anomaly narration: log to audit trail

---

### Phase 6: Testing
**Goal:** 15+ prompt eval cases for A2, unit tests for all new endpoints.

#### 6.1 Unit tests — ai-agent
**File:** `services/ai-agent/tests/unit/features/test_account_suggest.py`
- Test multi-line suggestion parsing
- Test balance validation (lines must balance)
- Test out-of-chart rejection
- Test confidence threshold abstention
- Test explanation generation

#### 6.2 Unit tests — core
**File:** `services/core/tests/unit/features/finance/test_automation.py`
- Test `draft_entry` endpoint
- Test `narrate_anomaly` endpoint
- Test `generate_reminder` endpoint
- Test `batch_reminders` endpoint
- Test permission checks

#### 6.3 Prompt eval set
**New file:** `services/ai-agent/tests/eval/finance_prompt_eval.py`
- 15+ test cases covering:
  - Simple rent payment → 2-line balanced JE
  - Multi-account sentence → 3+ line balanced JE
  - Amount extraction from various formats
  - Confidence abstention for vague descriptions
  - Edge cases: no amount mentioned, multiple amounts, currency symbols

#### 6.4 Integration tests
**File:** `services/core/tests/integration/database/test_finance_ai.py`
- Test full round-trip: description → AI draft → apply to JE form
- Test reminder generation for overdue invoices
- Test anomaly narration with real anomaly data

---

## Migration Summary

### Core — new migration `0029`
- No new tables needed for A1/A2/A7 (existing `ai_finance_suggestions` and `ai_finance_anomalies` suffice)
- May add columns to `ai_finance_suggestions` for storing `lines` JSONB and `explanation` text

### AI-Agent — new migration `0014`
- `UPDATE agent_registry SET enabled = true WHERE name = 'finance_assistant'`

---

## File Change Summary

| # | File | Action | Phase |
|---|------|--------|-------|
| 1 | `ai-agent/api/v1/routers/account_suggest.py` | Fix SuggestResponse + add draft-entry endpoint | 1 |
| 2 | `ai-agent/features/account_suggest/schemas.py` | Add multi-line schemas | 1 |
| 3 | `ai-agent/features/account_suggest/suggest.py` | Enhanced multi-line prompt | 1 |
| 4 | `core/features/finance/automation.py` | Add draft-entry, narrate, reminder endpoints | 1,2,3 |
| 5 | `core/features/finance/ai_suggester.py` | Add draft_journal_entry, narrate_anomaly, generate_reminder | 1,2,3 |
| 6 | `core/features/finance/schemas.py` | Add request/response schemas | 1,2,3 |
| 7 | `core/features/finance/entities.py` | Add DraftEntry, DraftEntryLine, ReminderDraft | 1,2,3 |
| 8 | `core/features/finance/audit_events.py` | Add AI audit constants | 5 |
| 9 | `frontend/components/account-combobox.tsx` | Add sparkles icon + onSuggest prop | 1 |
| 10 | `frontend/components/ai-draft-dialog.tsx` | NEW — AI Draft dialog | 1 |
| 11 | `frontend/components/automation-widgets.tsx` | Update AnomalyFeed with narration | 2 |
| 12 | `frontend/journal-entries.tsx` | Multi-line prefill + AI Draft button | 1 |
| 13 | `frontend/invoice-detail.tsx` | Generate Reminder button | 3 |
| 14 | `frontend/invoices.tsx` | Batch reminder toolbar | 3 |
| 15 | `frontend/lib/api/finance-api.ts` | Add types + API functions | 1,2,3 |
| 16 | `ai-agent/features/supervisor/delegates.py` | Add FinanceAssistantDelegator | 4 |
| 17 | `ai-agent/features/supervisor/finance_gateway.py` | NEW — finance HTTP gateway | 4 |
| 18 | `ai-agent/features/supervisor/prompts.py` | Add FINANCE_SYSTEM_PROMPT | 4 |
| 19 | `ai-agent/features/supervisor/service.py` | Wire finance delegate | 4 |
| 20 | `ai-agent/graphs/supervisor.py` | Add finance_gateway_factory param | 4 |
| 21 | `ai-agent/api/lifespan.py` | Create FinanceGateway | 4 |
| 22 | `ai-agent/alembic/versions/0014_enable_finance_assistant.py` | NEW — enable agent | 4 |
| 23 | `core/alembic/versions/0029_finance_ai_extensions.py` | NEW — optional schema extensions | 5 |
| 24 | `ai-agent/tests/unit/features/test_account_suggest.py` | Update tests | 6 |
| 25 | `core/tests/unit/features/finance/test_automation.py` | Add tests | 6 |
| 26 | `ai-agent/tests/eval/finance_prompt_eval.py` | NEW — prompt eval set | 6 |

---

## Commit Split (per ticket spec)

1. **A1 fix + multi-line + sparkles UI** — Phases 1.1-1.10
2. **A2 drafter + validation + dialog UI** — Phase 1 (complete)
3. **Finance Advisor agent registration + chat tools** — Phase 4
4. **A7 narration + A8 reminders/batch + audits** — Phases 2, 3, 5

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Extend existing endpoint vs new | Extend suggest + new draft-entry | Backward compat for simple cases, new endpoint for complex |
| Dialog vs redirect | Dialog | Better UX, keeps user in context |
| Accept/reject per line | Yes | User controls exactly what goes into JE |
| Confidence gating | Abstention chip at < 0.75 | Prevents misleading suggestions |
| Reminder tone | Auto-selected, editable | Respects business rules while allowing override |
| Audit logging | Every action | Ticket requirement |
| Agent registration | Enable via migration | Consistent with existing pattern |

---

## Acceptance Criteria Checklist

- [ ] A1: POST /finance/ai/suggest-account returns ranked suggestions with RAG context
- [ ] A1: Sparkles icon beside every account dropdown
- [ ] A2: POST /finance/ai/draft-entry returns balanced JE draft
- [ ] A2: Prompt eval set >= 15 cases passes >= 80% structural validity
- [ ] A2: Unbalanced drafts explicitly flagged
- [ ] A2: "AI Draft" dialog with accept/reject per line
- [ ] A7: POST /finance/ai/narrate-anomaly returns plain-English explanation
- [ ] A7: Narration cites actual triggering figures
- [ ] A7: Narration rendered below anomaly badges
- [ ] A8: POST /finance/ai/reminder generates tiered reminder draft
- [ ] A8: Batch endpoint for all invoices > 30 days
- [ ] A8: "Generate Reminder" button on overdue invoice detail
- [ ] A8: Batch queue preview UI
- [ ] Finance Advisor agent enabled and responding
- [ ] All suggestion actions audited
- [ ] Permission keys erp.finance.ai.* enforced
- [ ] model_used recorded on every AI call

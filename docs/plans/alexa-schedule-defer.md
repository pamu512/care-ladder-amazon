# Alexa schedule, defer, and caregiver utterance deepen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
>
> **Status:** PLAN + BUILD (Anoop via Careladder-AWS: Plan and build). Draft PR from main. Do **not** merge. Do **not** Final Submit.
> **Repo:** `pamu512/care-ladder-amazon` @ main (CareConversation FSM + Alexa mobile ack already shipped).
> **Product lock unchanged:** Alexa primary, Fire TV supporting, caregiver on Alexa mobile, not a medical device, will not call emergency / no auto-dial.

**Goal:** Deepen the existing Alexa skill + CareConversation FSM with a richer caregiver utterance set, an APL notify card, a no-ack soft-escalate timer ladder, lightweight schedule pinning, and a defer-to-X flow that fails back to the primary with a parallel monitored check-in.

**Architecture:** Extend `CareConversation`, `classify_caregiver_intent`, MCP tools, and `alexa_sim`. Do not add a second skill, Routines marketplace play, auto-dial, or remuxed demo video. Schedule learning is a small window counter next to `RoutineProfile`, not a new ML path.

**Tech Stack:** Python 3.12, existing FastAPI + MCP Streamable HTTP, pytest, YAML household plan. APL is a JSON document + datasource built in-process (no live Alexa console publish required).

## Global Constraints

- No em dashes in docs, spoken copy, APL labels, or VO notes.
- Wellness ladder, not a medical device. Emergency rung stays off and locked.
- Soft escalate and defer-fail never place a real or auto emergency call.
- Reserved NANP fiction phones only (`+12125550176` family).
- Do not commit secrets or fall model weights.
- Account linking / roster only as needed to resolve `alternate_contact` for call-X.
- Keep existing Path A (resident clear_ok / needs_human / silence) and first-wins ack.

---

## 0. Current extension points (verified)

| Piece | Where | Keep / extend |
| --- | --- | --- |
| FSM | `src/care_ladder/channels/care_conversation.py` | Add states, timers, named transitions |
| Caregiver classifier | `src/care_ladder/channels/caregiver_intent.py` | Add utterance buckets + slot parse |
| Resident classifier | `src/care_ladder/channels/response_intent.py` | Reuse for parallel monitored check-in |
| MCP + snapshot | `src/care_ladder/mcp_server/server.py` | New tools; existing snapshot contract |
| Alexa sim | `src/care_ladder/mcp_server/alexa_sim.py` | Optional defer / HowIsHousehold path |
| Hourly learning | `src/care_ladder/learning/profile.py` | Untouched; schedule pin is separate |
| Inform card | `inform_card()` | Keep 3 legacy actions; APL card is additive |
| Plan roster | `configs/amazon_demo_home.yaml` | caregiver + secondary; resolve names from these |

Existing states: `idle → speaker_window → family_paged → pressure → calling_1 → calling_2 → closed`.

Existing caregiver buckets: `im_on_it | call_mom_now | pass_to_next | outcome | unclear`.

Note: `on my way` currently classifies as `im_on_it`. This plan splits it to a named `on_my_way` transition. `I'm on it` / `got it` stay `im_on_it`.

---

## 1. Intents

### 1.1 Caregiver utterance set (beyond legacy ack)

| Intent id | Sample utterances | FSM transition | Spoken confirmation |
| --- | --- | --- | --- |
| `false_alarm` | "false alarm", "it's nothing", "stand down" | `false_alarm` → `closed` | "Got it. Marking this as a false alarm." |
| `on_my_way` | "on my way", "I'm coming over", "heading there" | `on_my_way` (stops escalate, owner set, ask outcome) | "Okay. I will hold further alerts while you are on the way." |
| `need_second_look` | "need a second look", "check again", "look again" | `need_second_look` → stay open, re-prompt resident (`speaker_window`) | "Understood. I will take another look and check in again." |
| `snooze_alert` | "snooze", "remind me later", "not now" | `snooze` → `snoozed` until `T_snooze` | "Snoozed. I will check back shortly." |
| `defer_escalation` | "call X instead", "try X instead", "page the neighbor" | `defer` → `deferred` with slot `alternate_contact` and deadline `T_defer` | "I will try {X} instead, and come back to you if they do not answer." |
| `how_is_household` | "how is the household", "any open alerts", "is it quiet" | no mutation; status read | Spoken status (last cue, last ack, open or quiet since). |

Classifier order (fail-closed, first match wins):

1. `defer_escalation` (must extract `alternate_contact` or return `unclear`)
2. `false_alarm`
3. `need_second_look`
4. `snooze_alert`
5. `on_my_way`
6. existing `pass_to_next` / `call_mom_now` / `im_on_it` / `outcome`
7. `how_is_household`
8. `unclear`

Slot: `alternate_contact` is the trimmed name after `call`/`try`/`page` and before `instead` (or the remainder after those verbs). Resolve against household roster: Primary contact, Secondary contact, plus any extra `roster` display names. Unknown name is still accepted as a label (sim notify), never as a phone dial.

### 1.2 Defer-fail primary direction intents

When state is `defer_failed`, primary utterances map to:

| Intent id | Sample | Next edge |
| --- | --- | --- |
| `try_other` | "try Y", "call the neighbor instead" | `deferred(Y)` new `T_defer` |
| `try_again` | "try X again", "try them again" | `deferred(X)` reset `T_defer` |
| `on_my_way` | "on my way" | stop escalate, owner = primary |
| `false_alarm` | "false alarm" | `closed` |
| `snooze_alert` | "snooze" | `snoozed` |

### 1.3 Parallel monitored check-in (reuse resident classifier)

| Bucket | Maps to report token |
| --- | --- |
| `clear_ok` | `monitored_ok` |
| `needs_human` | `monitored_needs_help` |
| `unclear` / silence | `monitored_silent` |

Not a fall-level cue. Soft phrase only: "Are you okay?"

---

## 2. APL notify card (slots)

Alexa Presentation Language document built by `apl_notify_card(...)`. Additive to `inform_card`. Fire TV may mirror fields; it is not the pager.

| Slot | Source | Notes |
| --- | --- | --- |
| `thumbnail` | last-frame placeholder or `blurred:{incident_id}` | Never a live camera feed |
| `householdLabel` | plan / conversation household id + "Resident" | Calm label, no clinical words |
| `timeSinceCue` | seconds since cue, rendered as "N min ago" / "just now" | Integer seconds in datasource |
| `cueText` | existing cue text | Unchanged |
| `countdownSec` | existing countdown | Unchanged |
| `actions` | on-screen buttons mirroring voice intents | See below |

On-screen actions (ids must match classifier / FSM):

1. `false_alarm` - False alarm
2. `on_my_way` - On my way
3. `need_second_look` - Need a second look
4. `snooze_alert` - Snooze
5. Keep the three legacy inform actions (`im_on_it`, `call_mom_now`, `pass_to_next`) so existing Path C still works.

APL JSON lives in-repo (`src/care_ladder/channels/apl_notify.py`). No second skill package. Datasource key: `notify`.

---

## 3. FSM edges

### 3.1 New states

```
idle, speaker_window, family_paged, pressure, calling_1, calling_2, closed
+ snoozed
+ deferred
+ defer_failed
+ soft_reprompt
+ soft_next
```

`deferred` and `defer_failed` are open (join same thread). `snoozed` is open. Soft-escalate states are open and pageable.

### 3.2 Named transitions (caregiver)

```
pageable --false_alarm--> closed
pageable --on_my_way--> (same state, escalation_stopped, owner set, ask_outcome)
pageable --need_second_look--> speaker_window  (incident kept, family already informed)
pageable --snooze--> snoozed
pageable|soft_*|pressure --defer(X)--> deferred
deferred --ack_by_X--> (escalation_stopped, owner=X)
deferred --T_defer timeout--> defer_failed
defer_failed --try_other(Y)--> deferred
defer_failed --try_again--> deferred  (same X)
defer_failed --on_my_way|false_alarm|snooze--> as above
snoozed --T_snooze timeout--> family_paged  (re-notify, not a new fall)
```

`pageable` here means `family_paged | pressure | calling_1 | calling_2 | soft_reprompt | soft_next | defer_failed`.

`need_second_look` does **not** close and does **not** start a new incident. It re-enters `speaker_window` for another resident check-in on the same thread.

`on_my_way` is first-wins like legacy ack: later conflicting acks do not steal ownership.

### 3.3 Soft escalate (no-ack) edges

```
family_paged --T_reprompt, no caregiver intent--> soft_reprompt
soft_reprompt --T_next, still no intent--> soft_next
soft_next --stop--> stay (notify next roster / louder phrase already sent)
```

Hard stop: `soft_next` must **not** call `start_call`, `request_call`, or `emergency`. The existing `calling_1` / `calling_2` path remains only for an explicit `call_mom_now` / MCP `request_call` after a human chose it. Silence alone never auto-dials.

### 3.4 Schedule edges (not fall-level)

```
observe window --> count++
count >= N_REPEATS --> propose_pin (await caregiver confirm)
confirm_pin --> pin stored; roster informed "schedule pinned"
pinned window time shifts --> roster alert "schedule changed"
missed adherence on a pinned window --> start soft escalate (family_paged / soft_*), never distress/fall cue
```

---

## 4. Timers

All timers are explicit integers on `CareConversation` (seconds). Tests inject `now=` rather than sleeping. Defaults (demo-honest, short enough to tick in tests):

| Timer | Default | From | Fires |
| --- | --- | --- | --- |
| `T_reprompt` | 60 | `family_paged_at` | louder re-prompt to current roster slot |
| `T_next` | 60 | `soft_reprompt_at` | next roster name + louder phrase |
| `T_snooze` | 300 | `snoozed_at` | return to `family_paged` and re-notify |
| `T_defer` | 90 | `deferred_at` | `defer_failed` + parallel check-in |

`tick(now)` is the only clock driver. If `escalation_stopped` or `state == closed`, tick is a no-op.

Louder phrase (no medical claim): "Still waiting on a reply. Care Ladder needs a caregiver."

Next-roster phrase: "No reply from {current}. Notifying {next}. This is not a phone call."

---

## 5. Defer-fail flow (normative)

1. Primary (or current owner) says "call X instead" while escalating.
2. FSM: `deferred`, `deferred_to=X`, `defer_deadline=now+T_defer`.
3. Spoken ack to the speaker. Simulated notify to X includes household, cue text, time since cue, and that they were asked to take this instead of the primary.
4. If X acks before deadline: first-wins stop, owner=X, ask outcome. Primary is told X has it.
5. If X does not ack by `T_defer`:
   - State → `defer_failed`.
   - **In parallel** (same tick, two audit events):
     - Soft check-in to the monitored person: "Are you okay?" → `monitored_ok | monitored_needs_help | monitored_silent`.
     - Notify **primary** with: X did not answer; monitored report token; ask-for-direction actions (`try_other`, `try_again`, `on_my_way`, `false_alarm`, `snooze_alert`).
   - Primary reply drives the next edge (section 1.2).
6. Never auto-dial X, Y, or emergency. "Call X instead" means notify/page X on Alexa mobile, not PSTN.

---

## 6. File map

```
# NEW
docs/plans/alexa-schedule-defer.md          # this plan
src/care_ladder/channels/apl_notify.py      # APL document + datasource
src/care_ladder/learning/schedule.py        # repeating windows, pin, miss
tests/test_apl_notify.py
tests/test_schedule_pin.py
tests/test_defer_and_soft_escalate.py

# MODIFY
src/care_ladder/channels/care_conversation.py
src/care_ladder/channels/caregiver_intent.py
src/care_ladder/mcp_server/server.py
src/care_ladder/mcp_server/alexa_sim.py     # only if a tiny path is needed
tests/test_care_conversation_fsm.py
tests/test_caregiver_intent.py
tests/test_alexa_mobile_ack.py
tests/test_mcp_server.py                    # EXPECTED_TOOLS
README.md                                   # tool list only, story unchanged
```

Will **not** create: second skill, Routines listing, remuxed mp4, fall weights, WA/TG adapters.

---

## 7. Tasks

### Task 1: Plan lock

- [ ] This file in `docs/plans/alexa-schedule-defer.md`
- [ ] Commit: `docs: Alexa schedule and defer plan`

### Task 2: Caregiver intents (TDD)

**Files:** `caregiver_intent.py`, `test_caregiver_intent.py`

- [ ] Failing tests for FalseAlarm, OnMyWay, NeedSecondLook, SnoozeAlert, DeferEscalation+slot, HowIsHousehold
- [ ] `on my way` is `on_my_way`, not `im_on_it`
- [ ] Empty / groan stay `unclear`
- [ ] Implement classifier + `extract_alternate_contact` + spoken map
- [ ] Green + commit

### Task 3: FSM edges + timers (TDD)

**Files:** `care_conversation.py`, `test_care_conversation_fsm.py`, `test_defer_and_soft_escalate.py`

Interfaces to add:

- `false_alarm(by, raw) -> CareState`
- `on_my_way(by, raw) -> CareState`
- `need_second_look(by, raw) -> CareState`
- `snooze(by, raw, *, now, t_snooze=T_SNOOZE) -> CareState`
- `defer(alternate_contact, by, raw, *, now, t_defer=T_DEFER) -> CareState`
- `tick(now) -> CareState`
- `record_monitored_checkin(raw) -> Literal[monitored_ok, monitored_needs_help, monitored_silent]`
- `primary_direction(intent, *, alternate=None, by, raw, now) -> CareState`
- `household_status() -> dict`

- [ ] Failing tests for every edge in sections 3 and 5
- [ ] Soft escalate stops before dial (`start_call` never invoked by tick)
- [ ] Defer-fail emits primary ask + monitored report on the same tick
- [ ] Minimal implementation
- [ ] Green + commit

### Task 4: APL card (TDD)

**Files:** `apl_notify.py`, `test_apl_notify.py`

- [ ] Card has thumbnail, householdLabel, timeSinceCue, actions mirroring voice intents
- [ ] No em dashes in labels
- [ ] `notify_caretaker` MCP payload includes `apl_card`
- [ ] Green + commit

### Task 5: Schedule pin (TDD)

**Files:** `learning/schedule.py`, `test_schedule_pin.py`

- [ ] Observe repeating hour windows; after `N_REPEATS=3` propose pin
- [ ] Confirm pin (caregiver)
- [ ] Schedule change alerts roster (audit payload, simulated notify)
- [ ] Missed adherence returns `soft_escalate` (not fall / not distress)
- [ ] Green + commit

### Task 6: MCP + HowIsHousehold

**Files:** `server.py`, `test_alexa_mobile_ack.py`, `test_mcp_server.py`

New or extended tools (session_snapshot on every return):

- `caregiver_ack` accepts the new action ids / utterances
- `defer_escalation(household_id, incident_id, alternate_contact, utterance="")`
- `tick_care_timers(household_id, incident_id, now_iso="")`
- `how_is_household(household_id)`
- `confirm_schedule_pin(household_id, window="")`

- [ ] EXPECTED_TOOLS updated
- [ ] HowIsHousehold returns last cue, last ack, open or quiet since
- [ ] Green + commit

### Task 7: Acceptance

- [ ] `python -m pytest -v` green
- [ ] Draft PR summarizing new intents/states
- [ ] No merge, no Final Submit

---

## 8. Acceptance criteria

1. Plan doc is in the PR.
2. Tests cover: defer, defer_failed → primary ask + parallel monitored check-in, soft escalate timers, new caregiver intents.
3. pytest green (project command: `python -m pytest -v`).
4. Draft PR opened with a summary of new intents and states.
5. Product story unchanged: Alexa primary, Fire TV supporting, caregiver on Alexa mobile, not a medical device, no emergency auto-dial.

---

## 9. What we will not do

- Second Alexa skill or Routines marketplace listing
- Auto-dial emergency or enabling the emergency rung
- Remux the demo video (existing VO already matches the product lock)
- Commit secrets or fall model weights
- WhatsApp / Telegram adapters
- Merge to main or Final Submit

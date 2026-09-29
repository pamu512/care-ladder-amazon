# Proactive Events honesty (Amazon track)

Thin awareness layer only. Not the caregiver pager. Not a substitute for
Alexa mobile conversational ack.

## What this is

An optional, feature-flagged stub (`CARE_LADDER_PROACTIVE`, default **off**)
that can emit a local-sim **awareness chime** ("check the Alexa app") when
the FSM enters `family_paged`. The chime is meant to fan a person into the
Alexa mobile skill session, where the inform card and three actions live.

`send_awareness_chime(household_id, incident_id)` always returns
`simulated: true`. When the flag is off it returns `skipped: true`.

## What this is not

- Not a free-form notification API. Alexa Proactive Events / skill messaging
  is **schema-locked**. Catalogs constrain content.
- Not rich buttons. The three actions ("I'm on it", "Call Mom now",
  "Can't take it") are **not** delivered by Proactive Events. They happen
  inside the skill session after the person opens it.
- Not required for the demo. The sim path (`alexa_sim` + MCP notify/ack)
  works with the flag off. Do not claim push buttons arrived via PE.
- Not available as a real Amazon call in this hackathon window. This is
  **local sim only**. If a live catalog were approved later, the stub is the
  seam; the honesty limits stay.

## Demo language

If a chime is shown at all, say **awareness chime**. Actions happen in the
Alexa mobile skill. Fire TV remains the living-room timeline, not the pager.

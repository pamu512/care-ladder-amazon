"""Simulated Alexa+ agent: an MCP CLIENT that drives the Care Ladder over
Streamable HTTP, with a visible terminal transcript.

This is the demo path proving the MCP tools are callable at runtime by an
agent (PRD 7: simulated Alexa+ web experience allowed with sim source in
repo). Run standalone:

    .venv/bin/python -m care_ladder.mcp_server.alexa_sim --url http://127.0.0.1:8000/mcp

or call run_sim() from tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _session_banner(payload: dict) -> str:
    snap = payload.get("session_snapshot") or {}
    hh = snap.get("household_id") or payload.get("household_id") or "?"
    iid = snap.get("incident_id") or payload.get("incident_id") or "?"
    rung = snap.get("rung", payload.get("rung", 0))
    status = snap.get("status", payload.get("status"))
    return f"SESSION {hh}:{iid} rung={rung} status={status}"


async def _call(session: ClientSession, name: str, args: dict, log: list[str]) -> dict:
    result = await session.call_tool(name, args)
    payload = result.structured_content or {}
    line = f"ALEXA+ -> {name}({json.dumps(args)}) => {json.dumps(payload)[:140]}"
    log.append(line)
    print(line)
    banner = _session_banner(payload)
    log.append(banner)
    print(banner)
    return payload


async def run_sim(
    base_url: str = "http://127.0.0.1:8000",
    *,
    cue_kind: str = "no_movement",
    answer: str = "",
    verbose: bool = True,
) -> tuple[list[str], dict]:
    """Drive one incident through the MCP tools; return (transcript, final state)."""
    log: list[str] = []
    _streams = streamable_http_client(base_url.rstrip("/") + "/mcp")
    # SDK 2.x yields (read, write, get_session_id) - or (read, write) on older builds.
    async with _streams as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            log.append("ALEXA+ agent initialized (MCP Streamable HTTP)")
            if verbose:
                print(log[-1])

            started = await _call(
                session,
                "start_or_resume_incident",
                {"cue_kind": cue_kind, "household_id": "amazon-demo-1"},
                log,
            )
            iid = started["incident_id"]
            hh = started.get("household_id") or "amazon-demo-1"

            resumed = await _call(
                session,
                "start_or_resume_incident",
                {"cue_kind": cue_kind, "household_id": hh, "incident_id": iid},
                log,
            )
            if resumed.get("resumed"):
                resume_line = f"ALEXA+ resume-same-incident {iid}"
                log.append(resume_line)
                print(resume_line)

            if answer:
                chk = await _call(
                    session,
                    "check_in_prompt",
                    {"household_id": hh, "incident_id": iid, "utterance": answer},
                    log,
                )
                intent = chk.get("response_intent")
                log.append(
                    f"ALEXA+ intent {intent} ({chk.get('intent_label')}) "
                    f"raw={chk.get('raw')!r}"
                )
                if intent == "clear_ok":
                    final = await _call(
                        session,
                        "resolve_incident",
                        {"household_id": hh, "incident_id": iid, "reason": "voice_ok"},
                        log,
                    )
                    return log, final
                if intent == "needs_human":
                    await _call(
                        session,
                        "notify_caretaker",
                        {"household_id": hh, "incident_id": iid},
                        log,
                    )
                    status = await _call(
                        session,
                        "get_incident_status",
                        {"household_id": hh, "incident_id": iid},
                        log,
                    )
                    return log, status
                # unclear: same as no clear answer — fall through to notify

            # silence path: wait window closes -> notify -> offer call
            status = await _call(
                session, "get_incident_status", {"household_id": hh, "incident_id": iid}, log
            )
            await _call(session, "notify_caretaker", {"household_id": hh, "incident_id": iid}, log)
            call = await _call(
                session, "request_call", {"household_id": hh, "incident_id": iid}, log
            )
            log.append(
                f"Call requested to {call.get('phone_e164')} (simulated={call.get('simulated')})"
            )
            return log, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulated Alexa+ agent (MCP client)")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--cue", default="no_movement",
                        choices=["no_movement", "no_visibility", "distress_heuristic"])
    parser.add_argument("--answer", default="", help="Resident scripted utterance ('' = silence)")
    args = parser.parse_args()
    log, final = asyncio.run(run_sim(args.url, cue_kind=args.cue, answer=args.answer))
    print("---")
    print(f"final: {json.dumps(final)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

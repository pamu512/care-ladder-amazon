"""Fire TV caregiver app (slice 4): served HTML anchors + full API-driven flow."""

import json

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_firetv_served_with_calm_care_tech_tokens():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.get("/firetv/")
        assert r.status_code == 200
        html = r.text
        # design-system lock anchors
        for token in ("#24221E", "#A8B5A0", "#D9A05B", "#D98873", "#9DB0C7",
                      "JetBrains Mono", "Instrument Sans"):
            assert token in html, token
        # d-pad focus machinery
        assert "spatialMove" in html and "ArrowLeft" in html
        # states + copy anchors (name-scrubbed to match demo VO)
        assert "Resident's home · Fire TV" in html
        assert "Meera" not in html
        assert "Anoop" not in html
        assert "(555) 010-2276" in html
        assert "Wellness ladder — not a medical device" in html
        assert "Emergency dial off by default" in html
        # demo console drives the real API
        assert 'data-fixture="alexa_path_a"' in html
        assert 'data-fixture="alexa_path_a_soft_ok"' in html
        assert 'data-fixture="alexa_path_a_needs_human"' in html
        assert 'data-fixture="alexa_path_a_unclear"' in html
        assert 'data-fixture="alexa_path_b"' in html
        assert "Clear OK" in html and "Needs human" in html
        assert "t-intent" in html
        assert "/demo/run" in html and "/incidents" in html
        # poll the newest household incident (dict insertion order is oldest-first)
        assert "mine[mine.length - 1]" in html
        # emergency gate present + hard-locked copy
        assert "gateHold" in html and "Hard-locked in this build" in html
        # audit trail section
        assert "Audit trail" in html
        # privacy: silhouette only, no video element
        assert "<video" not in html
        # Ambient Hearth hierarchy: presence panel + first-class ladder rail
        assert 'class="presence"' in html
        assert 'class="rail"' in html
        assert "Escalation ladder" in html
        # six incident phases remain in the TV state machine
        for phase in ("allclear", "recheck", "checkin", "notify", "occluded", "resolved"):
            assert phase in html, phase
        # fonts are actually loaded (not merely named in a fallback stack)
        assert "@font-face" in html
        assert "url(" in html
        # shipping copy: resident / primary contact — no personal names
        assert "the resident" in html
        assert "primary contact" in html
        # Rank 1: Ambient Hearth same-incident memory, human rail labels
        assert "same incident · Alexa+ agent remembers" in html
        assert "Alexa+ voice check-in ×2" in html
        # transcript keeps intent + raw on soft OK / needs-human
        assert "d.reply_raw" in html and "d.intent_label" in html
        assert "t-intent" in html
        assert html.index("renderTranscript(inc)") < html.index("phase === 'resolved'")
        # quiet MCP flag for judge zoom; timestamps stay mono
        assert "via mcp" in html
        assert "d.via === 'mcp'" in html or 'd.via === "mcp"' in html
        assert "--font-mono" in html


def test_firetv_flow_path_a_then_ack():
    with TestClient(create_app(store=AuditStore())) as client:
        # fire Path A through the same endpoint the TV console uses
        r = client.post("/demo/run", json={"fixture": "alexa_path_a"})
        assert r.status_code == 200
        iid = r.json()["incident_id"]

        # TV poll: household-filtered incident list finds it
        listing = client.get("/incidents").json()
        mine = [i for i in listing if i["household_id"] == "amazon-demo-1"]
        assert any(i["id"] == iid for i in mine)

        # full incident carries the trail the TV renders
        inc = client.get(f"/incidents/{iid}").json()
        tools = [e["tool"] for e in inc["events"]]
        assert "alexa_checkin" in tools and "notify_caretaker" in tools

        # ack from the TV closes the loop
        ack = client.post(f"/incidents/{iid}/ack",
                          json={"contact": "primary contact", "via": "fire_tv"})
        assert ack.status_code == 200
        inc2 = client.get(f"/incidents/{iid}").json()
        assert inc2["acked_by"] == "primary contact"
        assert any(e["tool"] == "notify" and e["detail"].get("action") == "caregiver_ack"
                   for e in inc2["events"])


def test_firetv_soft_ok_and_needs_human_keep_intent_and_raw():
    with TestClient(create_app(store=AuditStore())) as client:
        html = client.get("/firetv/").text
        assert html.index("renderTranscript(inc)") < html.index("phase === 'resolved'")
        for fixture, intent, label in (
            ("alexa_path_a_soft_ok", "clear_ok", "Clear OK"),
            ("alexa_path_a_needs_human", "needs_human", "Needs human"),
        ):
            r = client.post("/demo/run", json={"fixture": fixture})
            assert r.status_code == 200
            inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
            chk = next(e for e in inc["events"] if e["tool"] == "alexa_checkin")
            assert chk["detail"]["response_intent"] == intent
            assert chk["detail"]["intent_label"] == label
            assert chk["detail"]["reply_raw"]


def test_firetv_flow_path_b_occlusion_copy():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_b"})
        iid = r.json()["incident_id"]
        inc = client.get(f"/incidents/{iid}").json()
        assert inc["cue"]["kind"] == "no_visibility"
        # the TV renders "never claims distress" from this data
        notify = next(e for e in inc["events"] if e["tool"] == "notify_caretaker")
        assert notify["detail"]["basis"] == "camera_health_inform"

def test_firetv_learning_badge_present():
    from fastapi.testclient import TestClient
    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore

    with TestClient(create_app(store=AuditStore())) as client:
        html = client.get('/firetv/').text
        assert 'learnPill' in html
        assert 'Learning schedule' in html and 'Schedule settled' in html and 'Learning frozen' in html
        assert '/learning/amazon-demo-1' in html


def test_amazon_fixture_carries_learning_detail():
    from fastapi.testclient import TestClient
    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore

    with TestClient(create_app(store=AuditStore())) as client:
        client.post('/learning/amazon-demo-1/reset')
        r = client.post('/demo/run', json={'fixture': 'alexa_path_a'})
        after = client.get('/learning/amazon-demo-1').json()
        assert after['confirmed_ok_days'] >= 0  # silence path: no OK bump, but persisted state readable
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        learning = inc['cue']['detail'].get('learning')
        assert learning and learning['learning_phase'] in {'rapid', 'settled'}
        assert any(e['tool'] == 'routine_profile_update' for e in inc['events'])


def test_firetv_mcp_agent_pill_and_live_poll():
    """Calm MCP pill is off by default; TV re-polls same incident as events land."""
    with TestClient(create_app(store=AuditStore())) as client:
        html = client.get("/firetv/").text
        assert 'id="mcpPill"' in html
        assert "MCP agent active" in html
        assert "/mcp-agent" in html
        # default hidden so standby stays calm
        assert 'id="mcpPill" data-phase="mcp" hidden' in html
        # same-incident poll: event_count / reply, not just a new id
        assert "event_count" in html
        assert "seenSig" in html or "reply_raw" in html
        idle = client.get("/mcp-agent").json()
        assert idle["active"] is False


def _mcp_post(client: TestClient, body: dict):
    return client.post(
        "/mcp",
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )


def _parse_sse_or_json(resp):
    txt = resp.text
    if txt.startswith("event:") or txt.startswith("data:"):
        for line in txt.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"no data line in SSE: {txt[:200]}")
    return json.loads(txt)


def _tools_list_names(client: TestClient) -> set[str]:
    init = _mcp_post(client, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "care-ladder-test", "version": "0.1"},
        },
    })
    assert init.status_code == 200, init.text
    listed = _mcp_post(client, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    })
    assert listed.status_code == 200, listed.text
    return {t["name"] for t in _parse_sse_or_json(listed)["result"]["tools"]}


def test_firetv_agent_path_meta_default_hidden_ink40():
    """Caregiver footer: Agent path · MCP in ink-40, hidden until via=mcp events."""
    with TestClient(create_app(store=AuditStore())) as client:
        html = client.get("/firetv/").text
        assert "Agent path · MCP" in html
        assert 'id="agentPathMeta"' in html
        assert 'id="agentPathMeta" hidden' in html
        assert "var(--ink-40)" in html
        # shown only when this incident's events came from MCP — not a tool dump
        assert "hasMcpEvents" in html or "via === 'mcp'" in html or 'via === "mcp"' in html
        hero = html.split('<section class="hero"')[1].split("</section>")[0]
        assert "jsonrpc" not in hero.lower()
        assert "tools/call" not in hero
        assert "tools/list" not in hero


def test_firetv_agent_tools_toggle_default_hidden_matches_tools_list():
    """Demo console Show agent tools is off; expand lists the seven MCP names."""
    with TestClient(create_app(store=AuditStore())) as client:
        html = client.get("/firetv/").text
        assert "Show agent tools" in html
        assert 'id="cShowTools"' in html
        assert 'id="agentTools"' in html
        assert 'id="agentTools" hidden' in html
        assert 'id="cShowTools"' in html and 'aria-expanded="false"' in html
        # judge list lives in the demo console, not the 10-foot hero
        console = html.split('id="console"')[1].split("gate-backdrop")[0]
        hero = html.split('<section class="hero"')[1].split("</section>")[0]
        assert "Show agent tools" in console
        assert "agentTools" in console
        assert "jsonrpc" not in hero.lower()

        names = _tools_list_names(client)
        assert len(names) == 7, names
        for name in names:
            assert name in console, name
            assert name not in hero, name

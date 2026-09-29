"""Fire TV caregiver app (slice 4): served HTML anchors + full API-driven flow."""

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

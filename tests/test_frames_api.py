"""Pre-event frame serving: privacy-transformed PNGs from the incident store."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def _run(client: TestClient, fixture: str) -> str:
    r = client.post("/demo/run", json={"fixture": fixture})
    assert r.status_code == 200
    return r.json()["incident_id"]


def test_frames_listing_and_png_serving():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        inc_id = _run(client, "opencv_stillness")

        listing = client.get(f"/incidents/{inc_id}/frames")
        assert listing.status_code == 200
        body = listing.json()
        assert body["count"] == 2
        assert body["privacy"] == "blur"
        assert body["frame_urls"] == [
            f"/incidents/{inc_id}/frames/0",
            f"/incidents/{inc_id}/frames/1",
        ]

        png = client.get(f"/incidents/{inc_id}/frames/0")
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_frame_index_out_of_range_404_and_cross_incident_isolated():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        inc_a = _run(client, "opencv_stillness")
        inc_b = _run(client, "no_movement_silence")  # no frames attached

        assert client.get(f"/incidents/{inc_a}/frames/5").status_code == 404
        assert client.get(f"/incidents/{inc_a}/frames/-1").status_code == 404
        listing_b = client.get(f"/incidents/{inc_b}/frames").json()
        assert listing_b["count"] == 0
        assert listing_b["frame_urls"] == []

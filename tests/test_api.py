from datetime import timedelta

from fastapi.testclient import TestClient

from carekey.app import DEMO_KEY, create_app
from carekey.ring.webhook import sign


def client_for(ck):
    return TestClient(create_app(ck.settings, ck))


def test_full_visit_flow(ck, clock):
    c = client_for(ck)
    start = clock()
    r = c.post(
        "/api/visits",
        json={
            "visitor_name": "Priya",
            "role": "nurse",
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=45)).isoformat(),
        },
    )
    assert r.status_code == 200
    code = r.json()["code"]
    assert len(code) == 6

    # Nobody at the door yet: refused.
    assert c.post("/api/checkin", json={"code": code}).json()["granted"] is False

    # Simulated Ring doorbell press, then the code works.
    assert c.post("/api/demo/event", json={"kind": "doorbell"}).json()["event"]["kind"] == "button_press"
    decision = c.post("/api/checkin", json={"code": code}).json()
    assert decision["granted"] is True

    state = c.get("/api/state").json()
    assert state["lock"]["unlocked"] is True
    assert state["visits"][0]["status"] == "in_progress"
    assert any("arrived" in t["text"] for t in state["timeline"])


def test_webhook_rejects_bad_signature(ck):
    c = client_for(ck)
    raw = b'{"meta":{},"data":{"type":"button_press","attributes":{}}}'
    r = c.post("/webhooks/ring", content=raw, headers={"X-Signature": "sha256=bad"})
    assert r.status_code == 401


def test_webhook_accepts_signed_event(ck):
    c = client_for(ck)
    raw = (
        b'{"meta":{"request_id":"r1"},"data":{"id":"fake.front-door_button_press_1",'
        b'"type":"button_press","attributes":{"source":"fake.front-door","timestamp":1792486800000}}}'
    )
    r = c.post("/webhooks/ring", content=raw, headers={"X-Signature": sign(raw, DEMO_KEY)})
    assert r.status_code == 200
    assert len(ck.store.list_events()) == 1


def test_demo_advance_raises_late_alert(ck, clock):
    c = client_for(ck)
    start = clock()
    c.post(
        "/api/visits",
        json={
            "visitor_name": "Sam",
            "role": "cleaner",
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=60)).isoformat(),
        },
    )
    alerts = c.post("/api/demo/advance", json={"minutes": 20}).json()["alerts"]
    assert any("late" in a["text"] for a in alerts)


def test_ask_endpoint(ck):
    c = client_for(ck)
    c.post("/api/demo/event", json={"kind": "package"})
    answer = c.post("/api/ask", json={"question": "Is my parcel outside?"}).json()["answer"]
    assert answer.startswith("Yes")

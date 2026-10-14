from datetime import timedelta

from carekey.models import DoorEvent, EventKind, NewVisit, Severity

from .conftest import DOOR


def event(ck, clock, kind, sub_type=None, eid=None):
    ts = clock()
    ck.handle_event(
        DoorEvent(id=eid or f"{kind}-{ts.timestamp()}", device_id=DOOR, kind=kind, sub_type=sub_type, ts=ts)
    )


def alerts(ck):
    return [t for t in ck.store.list_timeline() if t.kind == "alert"]


def book(ck, clock, start_in=0, minutes=45):
    start = clock() + timedelta(minutes=start_in)
    return ck.create_visit(
        NewVisit(visitor_name="Priya", role="nurse", start=start, end=start + timedelta(minutes=minutes))
    )


def test_late_visit_alerts_once(ck, clock):
    book(ck, clock)
    clock.advance(10)
    assert ck.tick() == []
    clock.advance(6)
    new = ck.tick()
    assert len(new) == 1
    assert "16 minutes late" in new[0].text
    assert new[0].severity is Severity.WARNING
    clock.advance(1)
    assert ck.tick() == []  # deduplicated


def test_missed_visit_is_critical(ck, clock):
    book(ck, clock, minutes=30)
    clock.advance(31)
    texts = [a.text for a in ck.tick()]
    assert any("missed the visit" in t for t in texts)


def test_arrived_visit_raises_no_alert(ck, clock):
    _, code = book(ck, clock)
    event(ck, clock, EventKind.BUTTON_PRESS)
    assert ck.check_in(code).granted
    clock.advance(60)
    assert all("late" not in a.text and "missed" not in a.text for a in ck.tick())


def test_lingering_without_ringing(ck, clock):
    event(ck, clock, EventKind.MOTION, "human")
    clock.advance(2)
    event(ck, clock, EventKind.MOTION, "human")
    assert not alerts(ck)
    clock.advance(2)
    event(ck, clock, EventKind.MOTION, "human")
    found = [a for a in alerts(ck) if "without ringing" in a.text]
    assert len(found) == 1
    assert "4 minutes" in found[0].text


def test_no_linger_alert_when_doorbell_rang(ck, clock):
    event(ck, clock, EventKind.MOTION, "human")
    clock.advance(2)
    event(ck, clock, EventKind.BUTTON_PRESS)
    clock.advance(2)
    event(ck, clock, EventKind.MOTION, "human")
    assert not [a for a in alerts(ck) if "without ringing" in a.text]


def test_no_linger_alert_for_expected_visitor(ck, clock):
    book(ck, clock)
    event(ck, clock, EventKind.MOTION, "human")
    clock.advance(4)
    event(ck, clock, EventKind.MOTION, "human")
    assert not [a for a in alerts(ck) if "without ringing" in a.text]


def test_parcel_waiting_and_collected(ck, clock):
    event(ck, clock, EventKind.MOTION, "package_delivery", eid="pkg1")
    clock.advance(30)
    assert not [a for a in ck.tick() if "parcel" in a.text]
    clock.advance(31)
    assert [a for a in ck.tick() if "still outside" in a.text]


def test_parcel_not_flagged_after_door_opened(ck, clock):
    event(ck, clock, EventKind.MOTION, "package_delivery", eid="pkg2")
    clock.advance(5)
    event(ck, clock, EventKind.DOOR_OPENED)
    clock.advance(70)
    assert not [a for a in ck.tick() if "still outside" in a.text]


def test_quiet_morning(ck, clock):
    clock.advance(60)  # 10:00 UTC
    assert not [a for a in ck.tick() if "No front door activity" in a.text]
    clock.advance(61)  # 11:01
    assert [a for a in ck.tick() if "No front door activity" in a.text]


def test_parent_check_in_prevents_quiet_morning(ck, clock):
    ck.parent_ok()
    clock.advance(130)
    assert not [a for a in ck.tick() if "No front door activity" in a.text]


def test_agent_rules_answers(ck, clock):
    event(ck, clock, EventKind.MOTION, "package_delivery", eid="pkg3")
    clock.advance(180)
    answer = ck.ask("Is my parcel still outside?")
    assert answer.startswith("Yes")
    assert "09:00" in answer and "3 hours ago" in answer
    ck.package_collected("pkg3")
    assert "brought in" in ck.ask("where is my package")


def test_visit_status_shows_late(ck, clock):
    visit, _ = book(ck, clock)
    clock.advance(16)
    state = ck.state()
    assert state["visits"][0]["status"] == "late"
    assert "hasn't arrived yet" in ck.ask("Is the nurse coming?")

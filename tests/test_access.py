from datetime import timedelta

from carekey.models import DoorEvent, EventKind, NewVisit

from .conftest import DOOR


def book(ck, clock, start_in=0, minutes=45, name="Priya", role="nurse"):
    start = clock() + timedelta(minutes=start_in)
    return ck.create_visit(
        NewVisit(visitor_name=name, role=role, start=start, end=start + timedelta(minutes=minutes))
    )


def doorbell(ck, clock, device=DOOR):
    ts = clock()
    ck.handle_event(
        DoorEvent(id=f"bp-{ts.timestamp()}", device_id=device, kind=EventKind.BUTTON_PRESS, ts=ts)
    )


def test_valid_code_with_someone_at_door_unlocks(ck, clock):
    visit, code = book(ck, clock)
    doorbell(ck, clock)
    decision = ck.check_in(code)
    assert decision.granted
    assert ck.lock.is_unlocked(clock())
    assert ck.store.get_visit(visit.id).checked_in_at == clock()


def test_valid_code_but_nobody_at_door_is_refused(ck, clock):
    _, code = book(ck, clock)
    decision = ck.check_in(code)
    assert not decision.granted
    assert "Ring hasn't seen anyone" in decision.reason
    assert not ck.lock.is_unlocked(clock())


def test_event_from_another_camera_does_not_count(ck, clock):
    _, code = book(ck, clock)
    doorbell(ck, clock, device="back-garden")
    assert not ck.check_in(code).granted


def test_old_doorbell_press_does_not_count(ck, clock):
    _, code = book(ck, clock)
    doorbell(ck, clock)
    clock.advance(10)
    assert not ck.check_in(code).granted


def test_code_is_single_use(ck, clock):
    _, code = book(ck, clock)
    doorbell(ck, clock)
    assert ck.check_in(code).granted
    second = ck.check_in(code)
    assert not second.granted
    assert "already been used" in second.reason


def test_too_early_and_too_late(ck, clock):
    _, early_code = book(ck, clock, start_in=60, name="Early")
    doorbell(ck, clock)
    assert "too early" in ck.check_in(early_code).reason

    _, late_code = book(ck, clock, start_in=-60, minutes=30, name="Late")
    assert "ended" in ck.check_in(late_code).reason


def test_early_grace_period_allows_entry(ck, clock):
    _, code = book(ck, clock, start_in=10)
    doorbell(ck, clock)
    assert ck.check_in(code).granted


def test_wrong_codes_trigger_lockout(ck, clock):
    _, code = book(ck, clock)
    doorbell(ck, clock)
    for _ in range(5):
        assert not ck.check_in("000000" if code != "000000" else "111111").granted
    blocked = ck.check_in(code)
    assert not blocked.granted
    assert "Too many wrong codes" in blocked.reason


def test_check_out_locks_door(ck, clock):
    visit, code = book(ck, clock)
    doorbell(ck, clock)
    ck.check_in(code)
    clock.advance(1)
    assert ck.check_out(visit.id).checked_out_at == clock()
    assert not ck.lock.is_unlocked(clock())


def test_lock_relocks_after_window(ck, clock):
    _, code = book(ck, clock)
    doorbell(ck, clock)
    ck.check_in(code)
    clock.advance(ck.settings.unlock_seconds / 60 + 1)
    assert not ck.lock.is_unlocked(clock())

from datetime import datetime, timedelta, timezone

import pytest

from carekey.config import Settings
from carekey.ring.client import FakeRingClient
from carekey.service import CareKey, DemoClock
from carekey.store import Store
from carekey.vision import FakeDescriber

DOOR = "fake.front-door"


class FakeClock(DemoClock):
    """Deterministic clock starting at 09:00 UTC on a fixed day."""

    def __init__(self, start: datetime) -> None:
        super().__init__()
        self.start = start

    def __call__(self) -> datetime:
        return self.start + timedelta(seconds=self.offset_seconds)

    def advance(self, minutes: float) -> None:
        self.offset_seconds += minutes * 60


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))


@pytest.fixture
def settings() -> Settings:
    return Settings(db_path=":memory:", ring_front_door_device_id=DOOR, timezone="UTC")


@pytest.fixture
def ck(settings, clock) -> CareKey:
    return CareKey(
        settings,
        store=Store(":memory:"),
        ring=FakeRingClient(DOOR),
        describer=FakeDescriber(),
        now_fn=clock,
    )

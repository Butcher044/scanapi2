"""HH:MM validation and live rescheduling (APScheduler, no event loop needed)."""
import pytest

from app.scheduler import Scheduler, parse_time


@pytest.mark.parametrize("text,expected", [("10:00", (10, 0)), ("7:05", (7, 5)), (" 23:59 ", (23, 59)),
                                           ("00:00", (0, 0))])
def test_parse_time_ok(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["", "24:00", "12:60", "12", "12:5", "ab:cd", "12:00:00", "-1:00"])
def test_parse_time_rejects(text):
    with pytest.raises(ValueError):
        parse_time(text)


class _Runner:
    async def run_all(self):
        pass


def test_reschedule_changes_next_run():
    sched = Scheduler(_Runner(), "10:00")
    assert sched.time == "10:00"
    sched.reschedule("18:30")
    assert sched.time == "18:30"
    nxt = sched.next_run()
    assert (nxt.hour, nxt.minute) == (18, 30) and str(nxt.tzinfo) == "Europe/Moscow"


def test_bad_initial_time_falls_back_to_default():
    assert Scheduler(_Runner(), "nonsense").time == "10:00"

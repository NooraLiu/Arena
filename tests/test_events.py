import json
from arena.events import Event, EventLog


def test_event_log_serializes_to_jsonl():
    log = EventLog()
    log.record(Event(type="attack", round_no=2, actor=1,
                      visibility="public", payload={"target": 3, "damage": 4}))
    log.record(Event(type="eliminated", round_no=2, actor=3,
                      visibility="public", payload={}))
    lines = log.to_jsonl().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "attack" and first["payload"]["damage"] == 4

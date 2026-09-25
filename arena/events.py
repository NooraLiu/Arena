import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List


@dataclass
class Event:
    type: str
    round_no: int
    actor: Optional[int]
    visibility: str
    payload: Dict


@dataclass
class EventLog:
    events: List[Event] = field(default_factory=list)

    def record(self, event: Event) -> None:
        self.events.append(event)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(asdict(e), ensure_ascii=False) for e in self.events) + "\n"

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_jsonl())

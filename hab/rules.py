"""Automation rules: "when <device>.<field> <op> <value> then send <command> to <device>".

Rules live in a JSON file so they survive restarts and can be edited by hand,
from the dashboard API, or by the Claude bot.
"""

from __future__ import annotations

import json
import operator
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@dataclass
class Rule:
    name: str
    when_device: str
    when_field: str
    op: str
    value: Any
    then_device: str
    then_command: dict
    cooldown_s: int = 30
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def validate(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"op must be one of {sorted(OPS)}")
        if not isinstance(self.then_command, dict) or not self.then_command:
            raise ValueError("then_command must be a non-empty object, e.g. {\"on\": true}")

    def matches(self, state: dict) -> bool:
        if not self.enabled or self.when_field not in state:
            return False
        try:
            return OPS[self.op](state[self.when_field], self.value)
        except TypeError:  # e.g. comparing a string reading with a number
            return False


class RuleEngine:
    """Evaluates rules on every state update. A rule fires on the rising edge
    (condition goes false -> true) and then waits out its cooldown."""

    def __init__(self, path: Path, send: Callable[[str, dict], None]):
        self.path = path
        self.send = send
        self._lock = threading.Lock()
        self._was_true: dict[str, bool] = {}
        self._last_fired: dict[str, float] = {}
        self.log: list[dict] = []
        self.rules: dict[str, Rule] = {}
        if path.exists():
            for raw in json.loads(path.read_text()):
                rule = Rule(**raw)
                self.rules[rule.id] = rule

    def _save(self) -> None:
        self.path.write_text(json.dumps([asdict(r) for r in self.rules.values()], indent=2))

    def add(self, rule: Rule) -> Rule:
        rule.validate()
        with self._lock:
            self.rules[rule.id] = rule
            self._save()
        return rule

    def delete(self, rule_id: str) -> bool:
        with self._lock:
            found = self.rules.pop(rule_id, None) is not None
            if found:
                self._save()
        return found

    def on_state(self, device_id: str, state: dict, now: float | None = None) -> list[Rule]:
        now = time.time() if now is None else now
        fired = []
        with self._lock:
            rules = [r for r in self.rules.values() if r.when_device == device_id]
        for rule in rules:
            is_true = rule.matches(state)
            rising = is_true and not self._was_true.get(rule.id, False)
            self._was_true[rule.id] = is_true
            cooled = now - self._last_fired.get(rule.id, 0) >= rule.cooldown_s
            if rising and cooled:
                self._last_fired[rule.id] = now
                self.send(rule.then_device, rule.then_command)
                self.log.append({"ts": now, "rule": rule.name, "device": rule.then_device,
                                 "command": rule.then_command})
                self.log = self.log[-100:]
                fired.append(rule)
        return fired

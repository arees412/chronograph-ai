"""Provider-neutral in-process instrumentation boundary."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Protocol


class Instrumentation(Protocol):
    def increment(self, name: str, value: int = 1) -> None: ...
    def observe(self, name: str, value: float) -> None: ...


class InMemoryInstrumentation:
    def __init__(self) -> None:
        self.counters: dict[str, int] = defaultdict(int)
        self.observations: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        self.observations[name].append(value)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.observe(name, perf_counter() - started)

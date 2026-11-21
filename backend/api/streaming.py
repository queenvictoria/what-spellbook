"""Websocket transport for the operations that take long enough to watch.

The HTTP routes are still the contract: every one of them validates, calls one service
method and maps a typed error to a status code, and a client that only ever uses them
gets the whole application. This module exists for the handful of operations where
waiting silently is the actual problem - a recommendation is ~45 seconds, and the
browser's progress display had to *guess* which stage was running from a stopwatch.

The service already announces its stages (``progress=emit``) for the CLI. The same
callback is bridged back onto the event loop here, so the stage a browser sees is the
stage the work is actually in rather than an elapsed-time heuristic.

Three decisions worth keeping:

* **The unit of a message is one operation, not one connection.** A socket stays open for
  the life of the panel that opened it, so a follow-up question ("and a grapple?") costs
  no new handshake and keeps its ordering with the answer before it.
* **Progress and result travel on the same channel.** A client that has to poll a second
  endpoint for the result would still be guessing when to stop, which is the thing this
  replaces. ``result`` is terminal and unambiguous.
* **An error is a message, not a close.** A model that is down is a normal outcome a
  panel renders, and closing the socket would also throw away the conversation it was in
  the middle of. The codes are the HTTP codes, so the two transports cannot disagree
  about what a failure means.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

import anyio
from starlette.concurrency import run_in_threadpool

from backend.libs import timing


@dataclasses.dataclass
class Event:
    """One frame on the wire.

    ``type`` is the discriminant: ``start`` (what this operation will run through),
    ``stage`` (where it is now), ``result`` (the answer, terminal) and ``error`` (the
    failure, terminal). ``stages`` is only on ``start`` and is what lets a panel draw the
    whole list up front instead of appending as events arrive.
    """

    type: str
    id: str | None = None
    op: str | None = None
    key: str | None = None
    label: str | None = None
    stages: list[str] | None = None
    data: Any = None
    status: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        # Omit what is empty rather than sending nulls, so "start" and "request" are not
        # ambiguous: a client can treat the presence of `stages` as the start frame and the
        # presence of `data` as the result, without also checking that the other is null.
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


def start(op: str, id: str | None = None) -> Event:
    return Event(type="start", id=id, op=op,
                 stages=list(timing.OPERATION_STAGES.get(op, ())))


def stage(message: str, id: str | None = None) -> Event:
    """A stage frame from the same string the CLI prints.

    The label is the service's own wording, so a browser does not have to keep a second copy
    of the vocabulary; the key is the stable identifier to switch on.
    """
    return Event(type="stage", id=id, key=timing.stage_key(message), label=message)


def result(op: str, data: Any, id: str | None = None) -> Event:
    return Event(type="result", id=id, op=op, data=data)


def error(op: str | None, status: int, detail: str, id: str | None = None) -> Event:
    return Event(type="error", id=id, op=op, status=status, detail=detail)


async def with_progress(send: Callable[[Event], Any], work: Callable[..., Any],
                        *, id: str | None = None) -> Any:
    """Run blocking ``work`` off the loop, forwarding its progress as it happens.

    ``work`` is handed an ``emit(message)`` callback, which is the same callable shape the
    CLI passes to the service. The service runs in a worker thread - it does blocking
    embedding and model calls - so the callback has to travel back to the event loop
    without blocking the thread it is on. ``anyio.from_thread.run_sync`` does exactly
    that, and ``send_nowait`` keeps the ordering that ``await`` would lose anyway once the
    thread's only job is to keep working.

    ``id`` is echoed on every frame so one socket can carry several operations at once -
    two panels, or a tab that started something and navigated away. Without it, frames from
    concurrent runs would interleave into one panel and the first ``result`` would be
    mistaken for the second run's.
    """
    events, receiver = anyio.create_memory_object_stream[Event](16)

    def emit(message: str) -> None:
        anyio.from_thread.run_sync(events.send_nowait, stage(message, id))

    async def pump() -> None:
        async with receiver:
            async for event in receiver:
                await send(event)

    async with anyio.create_task_group() as group:
        group.start_soon(pump)
        try:
            return await run_in_threadpool(work, emit)
        finally:
            # Closing before the group exits is what terminates the pump; without it the
            # group would wait for a stream that nothing is going to write to.
            events.close()


__all__ = [
    "Event",
    "start",
    "stage",
    "result",
    "error",
    "with_progress",
]
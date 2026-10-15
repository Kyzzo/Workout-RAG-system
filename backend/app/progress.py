# Progress stages for slow requests ("Searching the papers", "Checking 9
# statements..."), so the chat can show what it's doing during a ~45s
# answer. Code anywhere in a request calls report(label); it goes nowhere
# unless the request is being streamed (see routers/chat.py), which sets a
# reporter for the duration. A context variable, so concurrent requests
# never see each other's stages. Worker threads don't inherit it, so stages
# are reported from the request's own thread.
import contextvars
from contextlib import contextmanager
from typing import Callable

_reporter: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "progress_reporter", default=None,
)


def report(label: str) -> None:
    reporter = _reporter.get()
    if reporter is not None:
        reporter(label)


@contextmanager
def reporting(callback: Callable[[str], None]):
    token = _reporter.set(callback)
    try:
        yield
    finally:
        _reporter.reset(token)

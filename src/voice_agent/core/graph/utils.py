import asyncio
from dataclasses import dataclass
from typing import cast, Callable, Awaitable, TypeVar, Any

T = TypeVar("T")


@dataclass
class RunControl:
    """
    Runtime-only control object injected into state for the currently executing run.
    Must never be persisted.
    """
    set_interruptible: Callable[[bool], None]


async def run_non_interruptible(
    state: dict[str, Any],
    fn: Callable[[], Awaitable[T]],
) -> T:
    """
    Helper for critical sections inside LangGraph nodes.

    Usage:
        async def _commit():
            await confirm_appointment(...)

        await run_non_interruptible(state, _commit)

    This does two things:
    - marks the active run as non-interruptible from the engine's point of view
    - shields the actual critical awaitable from task cancellation
    """
    control = cast(RunControl | None, state.get("_run_control"))
    if control is not None:
        control.set_interruptible(False)

    try:
        return await asyncio.shield(fn())
    finally:
        if control is not None:
            control.set_interruptible(True)
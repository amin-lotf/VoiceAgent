from __future__ import annotations

import asyncio
import logging

import pytest

from voice_agent.logging import (
    LiveLogBroker,
    LiveLogEvent,
    LiveLogHandler,
    clear_live_log_persistence,
    configure_live_log_persistence,
)


@pytest.mark.asyncio
async def test_live_log_broker_replays_backlog_and_streams_new_events() -> None:
    broker = LiveLogBroker(buffer_size=5, queue_size=5)
    initial_event = LiveLogEvent(
        timestamp="2026-05-01T08:00:00+00:00",
        level="info",
        logger_name="voice_agent.core.graph.nodes.greeting",
        message="Greeting streamed",
        call_id="call-123",
        node="greeting",
        phase="greeting",
    )

    broker.publish(initial_event)
    subscriber, backlog = broker.subscribe("call-123")

    assert backlog == [initial_event]

    next_event = LiveLogEvent(
        timestamp="2026-05-01T08:00:01+00:00",
        level="debug",
        logger_name="voice_agent.core.graph.nodes.call_operator",
        message="Operator streamed token",
        call_id="call-123",
        node="call_operator",
        phase="collecting_info",
    )

    broker.publish(next_event)
    received = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)

    assert received == next_event
    broker.unsubscribe("call-123", subscriber)


@pytest.mark.asyncio
async def test_live_log_broker_filters_by_call_id() -> None:
    broker = LiveLogBroker(buffer_size=5, queue_size=5)
    subscriber, backlog = broker.subscribe("call-a")

    assert backlog == []

    broker.publish(
        LiveLogEvent(
            timestamp="2026-05-01T08:00:00+00:00",
            level="info",
            logger_name="voice_agent.test",
            message="Other call",
            call_id="call-b",
        )
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(subscriber.queue.get(), timeout=0.05)

    broker.unsubscribe("call-a", subscriber)


def test_live_log_handler_emits_to_registered_persistence_callback() -> None:
    captured: list[LiveLogEvent] = []
    handler = LiveLogHandler()

    configure_live_log_persistence(captured.append)
    try:
        record = logging.makeLogRecord(
            {
                "name": "voice_agent.core.graph.nodes.greeting",
                "msg": "Greeting completed",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "call_id": "call-789",
                "node": "greeting",
                "phase": "intent_routing",
            }
        )
        handler.emit(record)
    finally:
        clear_live_log_persistence()

    assert len(captured) == 1
    assert captured[0].call_id == "call-789"
    assert captured[0].logger_name == "voice_agent.core.graph.nodes.greeting"
    assert captured[0].message == "Greeting completed"
    assert captured[0].node == "greeting"
    assert captured[0].phase == "intent_routing"

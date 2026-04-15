import asyncio

import pytest

from voice_agent.core.graph.node_timing import (
    AI_DELAY_KEY,
    NON_AI_DELAY_KEY,
    TOTAL_DELAY_KEY,
    build_turn_timing_payload,
    record_node_ai_delay,
    reset_node_timing_data,
    with_node_timing,
)
from voice_agent.core.graph.nodes.planner import node_planner


@pytest.mark.asyncio
async def test_with_node_timing_records_delay_breakdown():
    async def fake_node(state):
        await asyncio.sleep(0.01)
        record_node_ai_delay(0.004)
        return {"assistant_text": "done"}

    timed_node = with_node_timing("fake_node", fake_node)

    result = await timed_node({"node_data": {}})
    bucket = result["node_data"]["fake_node"]

    assert bucket[AI_DELAY_KEY] == pytest.approx(0.004, abs=1e-6)
    assert bucket[TOTAL_DELAY_KEY] >= bucket[AI_DELAY_KEY]
    assert bucket[NON_AI_DELAY_KEY] == pytest.approx(
        bucket[TOTAL_DELAY_KEY] - bucket[AI_DELAY_KEY],
        abs=1e-6,
    )


def test_reset_node_timing_data_keeps_non_timing_fields():
    state = {
        "node_data": {
            "call_operator": {
                "raw_output": "hello",
                TOTAL_DELAY_KEY: 1.5,
                AI_DELAY_KEY: 0.9,
                NON_AI_DELAY_KEY: 0.6,
            },
            "planner": {
                "directives": ["a"],
            },
        }
    }

    reset_node_timing_data(state)

    assert state["node_data"]["call_operator"] == {"raw_output": "hello"}
    assert state["node_data"]["planner"] == {"directives": ["a"]}


@pytest.mark.asyncio
async def test_planner_reset_preserves_existing_timing_fields():
    state = {
        "node_data": {
            "user_intent": {
                TOTAL_DELAY_KEY: 1.2,
                AI_DELAY_KEY: 0.4,
                NON_AI_DELAY_KEY: 0.8,
            }
        }
    }

    result = await node_planner(state)

    assert result["node_data"]["user_intent"] == {
        TOTAL_DELAY_KEY: 1.2,
        AI_DELAY_KEY: 0.4,
        NON_AI_DELAY_KEY: 0.8,
    }


def test_build_turn_timing_payload_aggregates_ai_delay_from_nodes():
    payload = build_turn_timing_payload(
        state={
            "node_data": {
                "greeting": {
                    TOTAL_DELAY_KEY: 0.9,
                    AI_DELAY_KEY: 0.5,
                    NON_AI_DELAY_KEY: 0.4,
                },
                "call_operator": {
                    TOTAL_DELAY_KEY: 1.6,
                    AI_DELAY_KEY: 1.1,
                    NON_AI_DELAY_KEY: 0.5,
                },
            }
        },
        total_delay_s=3.0,
    )

    assert payload == {
        TOTAL_DELAY_KEY: 3.0,
        AI_DELAY_KEY: 1.6,
        NON_AI_DELAY_KEY: 1.4,
    }

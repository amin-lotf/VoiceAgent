import asyncio

import pytest

from voice_agent.core.graph.node_timing import (
    AI_DELAY_KEY,
    FIRST_TOKEN_DELAY_KEY,
    INPUT_TOKENS_KEY,
    NON_AI_DELAY_KEY,
    OUTPUT_TOKENS_KEY,
    TOTAL_DELAY_KEY,
    TOTAL_TOKENS_KEY,
    build_recorded_turn_metrics,
    build_turn_timing_payload,
    format_turn_timing_summary,
    summarize_recorded_turn_metrics,
    record_node_ai_delay,
    record_node_token_usage,
    reset_node_timing_data,
    with_node_timing,
)
from voice_agent.core.graph.nodes.planner import node_planner


@pytest.mark.asyncio
async def test_with_node_timing_records_delay_breakdown():
    async def fake_node(state):
        await asyncio.sleep(0.01)
        record_node_ai_delay(0.004)
        record_node_token_usage(
            {
                INPUT_TOKENS_KEY: 7,
                OUTPUT_TOKENS_KEY: 3,
                TOTAL_TOKENS_KEY: 10,
            }
        )
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
    assert bucket[INPUT_TOKENS_KEY] == 7
    assert bucket[OUTPUT_TOKENS_KEY] == 3
    assert bucket[TOTAL_TOKENS_KEY] == 10


def test_reset_node_timing_data_keeps_non_timing_fields():
    state = {
        "node_data": {
            "call_operator": {
                "raw_output": "hello",
                TOTAL_DELAY_KEY: 1.5,
                AI_DELAY_KEY: 0.9,
                NON_AI_DELAY_KEY: 0.6,
                INPUT_TOKENS_KEY: 20,
                OUTPUT_TOKENS_KEY: 4,
                TOTAL_TOKENS_KEY: 24,
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
                INPUT_TOKENS_KEY: 12,
                OUTPUT_TOKENS_KEY: 5,
                TOTAL_TOKENS_KEY: 17,
            }
        }
    }

    result = await node_planner(state)

    assert result["node_data"]["user_intent"] == {
        TOTAL_DELAY_KEY: 1.2,
        AI_DELAY_KEY: 0.4,
        NON_AI_DELAY_KEY: 0.8,
        INPUT_TOKENS_KEY: 12,
        OUTPUT_TOKENS_KEY: 5,
        TOTAL_TOKENS_KEY: 17,
    }


def test_build_turn_timing_payload_aggregates_ai_delay_from_nodes():
    payload = build_turn_timing_payload(
        state={
            "node_data": {
                "greeting": {
                    TOTAL_DELAY_KEY: 0.9,
                    AI_DELAY_KEY: 0.5,
                    NON_AI_DELAY_KEY: 0.4,
                    INPUT_TOKENS_KEY: 30,
                    OUTPUT_TOKENS_KEY: 10,
                    TOTAL_TOKENS_KEY: 40,
                },
                "call_operator": {
                    TOTAL_DELAY_KEY: 1.6,
                    AI_DELAY_KEY: 1.1,
                    NON_AI_DELAY_KEY: 0.5,
                    INPUT_TOKENS_KEY: 74,
                    OUTPUT_TOKENS_KEY: 25,
                    TOTAL_TOKENS_KEY: 99,
                },
            }
        },
        total_delay_s=3.0,
    )

    assert payload == {
        TOTAL_DELAY_KEY: 3.0,
        AI_DELAY_KEY: 1.6,
        NON_AI_DELAY_KEY: 1.4,
        INPUT_TOKENS_KEY: 104,
        OUTPUT_TOKENS_KEY: 35,
        TOTAL_TOKENS_KEY: 139,
    }


def test_build_recorded_turn_metrics_includes_first_token_delay():
    payload = build_recorded_turn_metrics(
        state={
            "node_data": {
                "call_operator": {
                    TOTAL_DELAY_KEY: 1.1,
                    AI_DELAY_KEY: 0.8,
                    NON_AI_DELAY_KEY: 0.3,
                    INPUT_TOKENS_KEY: 74,
                    OUTPUT_TOKENS_KEY: 25,
                    TOTAL_TOKENS_KEY: 99,
                }
            }
        },
        total_delay_s=1.4,
        first_token_delay_s=0.6,
    )

    assert payload == {
        TOTAL_TOKENS_KEY: 99,
        TOTAL_DELAY_KEY: 1.4,
        FIRST_TOKEN_DELAY_KEY: 0.6,
    }


def test_summarize_recorded_turn_metrics_aggregates_saved_turns():
    payload = summarize_recorded_turn_metrics(
        [
            {
                TOTAL_TOKENS_KEY: 99,
                TOTAL_DELAY_KEY: 1.4,
                FIRST_TOKEN_DELAY_KEY: 0.8,
            },
            {
                TOTAL_TOKENS_KEY: 17,
                TOTAL_DELAY_KEY: 1.2,
                FIRST_TOKEN_DELAY_KEY: 0.4,
            },
            {
                "role": "user",
                "content": "hello",
                TOTAL_TOKENS_KEY: None,
                TOTAL_DELAY_KEY: None,
                FIRST_TOKEN_DELAY_KEY: None,
            },
        ]
    )

    assert payload == {
        TOTAL_TOKENS_KEY: 116,
        "avg_total_delay_s": 1.3,
        "avg_first_token_delay_s": 0.6,
    }


def test_format_turn_timing_summary_includes_token_totals():
    summary = format_turn_timing_summary(
        state={
            "node_data": {
                "call_operator": {
                    TOTAL_DELAY_KEY: 1.1,
                    AI_DELAY_KEY: 0.8,
                    NON_AI_DELAY_KEY: 0.3,
                    INPUT_TOKENS_KEY: 74,
                    OUTPUT_TOKENS_KEY: 25,
                    TOTAL_TOKENS_KEY: 99,
                }
            }
        },
        total_delay_s=1.4,
    )

    assert summary == "turn: total=1.400s ai=0.800s non_ai=0.600s tokens=99 in=74 out=25"

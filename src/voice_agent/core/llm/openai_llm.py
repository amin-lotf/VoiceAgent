from __future__ import annotations

from langchain_openai import ChatOpenAI

from voice_agent.core.settings import settings


LLM = ChatOpenAI(
    model=settings.REPLY_MODEL,
    temperature=settings.REPLY_TEMPERATURE,
    api_key=settings.OPENAI_API_KEY,
    seed=settings.RANDOM_SEED,
)

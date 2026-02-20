import redis

from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.store.redis_store import RedisStateStore


def main():
    r = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )

    store = RedisStateStore(r, ttl_seconds=60 * 60)

    engine = InterviewEngine(store=store,sessionmaker=AsyncSessionLocal)
    engine._graph.get_graph().draw_mermaid_png(output_file_path='my_graph.png')
    # print(engine._graph.get_graph().draw_mermaid())


if __name__ == "__main__":
    main()
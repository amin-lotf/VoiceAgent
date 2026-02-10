"""Default (non-secret) configuration values used by BaseSettings."""

DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/talk_to_pdf"
DEFAULT_TEST_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/talk_to_pdf_test"


DEFAULT_REPLY_PROVIDER = "openai"
DEFAULT_REPLY_MODEL = "gpt-4o-mini"
DEFAULT_REPLY_TEMPERATURE = 0.2
DEFAULT_REPLY_MAX_OUTPUT_TOKENS = None
DEFAULT_REPLY_MAX_CONTEXT_CHARS = 20000


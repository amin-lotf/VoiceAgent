
import os
from voice_agent.const import DEFAULT_API_BASE_URL

BASE_URL = os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL)  # FastAPI root
# Streamlit UI

The working Streamlit UI remains under `src/voice_agent/frontend`.

That path is still the canonical runtime location because Streamlit multipage discovery relies on it. Moving the files directly would risk breaking the existing launch path and page routing.

Use this command:

```bash
uv run streamlit run src/voice_agent/frontend/streamlit_app.py
```

This directory exists as the frontend wrapper/documentation location. The React app source now lives at `src/voice_agent/frontend/react`.

# Streamlit UI

The working Streamlit UI remains under `src/voice_agent/frontend`.

That path is still the canonical runtime location because the current `talk` command and Streamlit multipage discovery rely on it. Moving the files directly would risk breaking the existing launch path and page routing.

Use these commands:

```bash
uv run streamlit run src/voice_agent/frontend/streamlit_app.py
```

or

```bash
uv run talk
```

This directory exists as the frontend wrapper/documentation location. The React app source now lives at `src/voice_agent/frontend/react`.

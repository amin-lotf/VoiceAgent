def estimate_speech_seconds(text: str) -> float:
    words = len(text.split())
    return max(3, min(1.5, words / 2.7))



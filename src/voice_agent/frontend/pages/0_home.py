import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import streamlit as st
from websocket import WebSocketApp

def stream_for_rid(target_rid: int):
    """
    Generator yielding token chunks for a specific response_id.
    Stops when content_complete=True for that response_id.
    """
    inbox: "queue.Queue[Dict[str, Any]]" = st.session_state["inbox"]

    while True:
        try:
            obj = inbox.get(timeout=0.1)
        except queue.Empty:
            continue

        # pass through connection / error events if you want (optional)
        if obj.get("_type") == "error":
            raise RuntimeError(obj.get("error", "ws error"))
        if obj.get("_type") in ("open", "close"):
            continue

        # Ignore non-response frames (e.g. config)
        if "response_id" not in obj:
            continue

        rid = int(obj["response_id"])
        if rid != target_rid:
            # IMPORTANT for barge-in: ignore chunks for other response_ids
            continue

        content = obj.get("content") or ""
        complete = bool(obj.get("content_complete", False))

        if content:
            yield content

        if complete:
            break

# -------------------------
# Retell-like payload helpers
# -------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def make_ping() -> Dict[str, Any]:
    return {"interaction_type": "ping_pong", "timestamp": now_ms()}


def make_response_required(response_id: int, transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "interaction_type": "response_required",
        "response_id": response_id,
        "transcript": transcript,
        "timestamp": now_ms(),
    }


# -------------------------
# Threaded WS client (Streamlit-friendly)
# -------------------------
@dataclass
class WsClient:
    url: str
    inbox: "queue.Queue[Dict[str, Any]]"
    wsapp: Optional[WebSocketApp] = None
    thread: Optional[threading.Thread] = None
    stop_flag: Optional[threading.Event] = None
    ping_thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        if self.wsapp is not None:
            return

        self.stop_flag = threading.Event()

        def on_message(ws, message: str):
            try:
                obj = json.loads(message)
                self.inbox.put(obj)
            except Exception:
                # Ignore non-JSON
                pass

        def on_error(ws, error):
            self.inbox.put({"_type": "error", "error": str(error)})

        def on_close(ws, code, reason):
            self.inbox.put({"_type": "close", "code": code, "reason": reason})

        def on_open(ws):
            self.inbox.put({"_type": "open"})

        self.wsapp = WebSocketApp(
            self.url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        def run_ws():
            # ping_interval=None because we do Retell-style pings ourselves
            self.wsapp.run_forever(ping_interval=None)

        self.thread = threading.Thread(target=run_ws, daemon=True)
        self.thread.start()

        # Retell-like ping loop
        def ping_loop():
            while self.stop_flag and not self.stop_flag.is_set():
                try:
                    if self.wsapp:
                        self.wsapp.send(json.dumps(make_ping()))
                except Exception:
                    pass
                time.sleep(2.0)

        self.ping_thread = threading.Thread(target=ping_loop, daemon=True)
        self.ping_thread.start()

    def send(self, payload: Dict[str, Any]) -> None:
        if not self.wsapp:
            raise RuntimeError("Not connected")
        self.wsapp.send(json.dumps(payload))

    def close(self) -> None:
        if self.stop_flag:
            self.stop_flag.set()
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass
        self.wsapp = None
        self.thread = None
        self.ping_thread = None
        self.stop_flag = None


# -------------------------
# Streamlit state
# -------------------------
def ensure_state() -> None:
    st.session_state.setdefault("messages", [])          # chat log
    st.session_state.setdefault("transcript", [])        # Retell transcript (user-only ok for your server)
    st.session_state.setdefault("streams", {})           # rid -> partial assistant text
    st.session_state.setdefault("response_id", 1)
    st.session_state.setdefault("client", None)
    st.session_state.setdefault("inbox", queue.Queue())
    st.session_state.setdefault("ws_status", "disconnected")
    st.session_state.setdefault("last_error", "")
    st.session_state.setdefault("stream_greeting_now", False)


def send_user_message(text: str) -> None:
    # show user message
    st.session_state["messages"].append({"role": "user", "content": text})
    st.session_state["transcript"].append({"role": "user", "content": text})

    # new response_id -> this is how you test barge-in
    rid = int(st.session_state["response_id"])
    st.session_state["response_id"] = rid + 1

    # send request
    payload = make_response_required(rid, st.session_state["transcript"])
    st.session_state["client"].send(payload)

    # STREAM assistant for this rid
    with st.chat_message("assistant"):
        final_text = st.write_stream(stream_for_rid(rid))

    # persist assistant message
    st.session_state["messages"].append({"role": "assistant", "content": final_text, "rid": rid})



# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="Retell WS Tester", layout="centered")
ensure_state()

st.title("Retell WS Tester (Streaming + Barge-in)")

with st.sidebar:
    st.subheader("Connection")
    if st.button("Open Calls Dashboard", use_container_width=True):
        st.switch_page("pages/1_dashboard.py")

    default_call_id = st.session_state.get("call_id") or f"test-{uuid.uuid4().hex[:8]}"
    call_id = st.text_input("call_id", value=default_call_id)
    st.session_state["call_id"] = call_id

    default_base = st.session_state.get("base_url") or "ws://localhost:8000"
    base_url = st.text_input("Base WS URL", value=default_base)  # must be ws:// or wss://
    st.session_state["base_url"] = base_url

    ws_url = f"{base_url.rstrip('/')}/api/v1/retell/llm/{call_id}"
    st.code(ws_url)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Connect", use_container_width=True, disabled=st.session_state["client"] is not None):
            st.session_state["inbox"] = queue.Queue()
            client = WsClient(url=ws_url, inbox=st.session_state["inbox"])
            client.connect()
            st.session_state["client"] = client
            st.session_state["ws_status"] = "connecting"

            # DON'T render greeting here (sidebar). Just schedule it.
            st.session_state["stream_greeting_now"] = True

    with c2:
        if st.button("Disconnect", use_container_width=True, disabled=st.session_state["client"] is None):
            st.session_state["client"].close()
            st.session_state["client"] = None
            st.session_state["ws_status"] = "disconnected"

    st.write(f"Status: **{st.session_state['ws_status']}**")
    if st.session_state.get("last_error"):
        st.error(st.session_state["last_error"])

    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state["messages"] = []
        st.session_state["transcript"] = []
        st.session_state["streams"] = {}
        st.session_state["response_id"] = 1
        st.session_state["current_assistant_text"] = ""
        st.session_state["current_assistant_rid"] = None

# Stream greeting in MAIN area (not sidebar)
if st.session_state.get("stream_greeting_now"):
    st.session_state["stream_greeting_now"] = False

    with st.chat_message("assistant"):
        greeting = st.write_stream(stream_for_rid(0))
    st.session_state["messages"].append({"role": "assistant", "content": greeting, "rid": 0})

    st.rerun()



# Render chat history
for m in st.session_state["messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])



# Input
disabled = st.session_state["client"] is None
prompt = st.chat_input("Type a message — send again while it streams to barge-in…", disabled=disabled)

if prompt and not disabled:
    send_user_message(prompt)
    st.rerun()


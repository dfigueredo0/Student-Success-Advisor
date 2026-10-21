"""Debug harness for the chat API: messages, state, tool calls, trace link.

make api-debug  # in one terminal (normal `make api` hides state and tool calls)
make harness    # in another
"""

import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="SSA harness", layout="wide")
st.title("Student Success Advisor - harness")

if st.sidebar.button("New conversation"):
    st.session_state.clear()
last = st.session_state.get("last")
st.sidebar.text_input("thread_id", value=last["thread_id"] if last else "", disabled=True)

chat_col, debug_col = st.columns([3, 2])

if prompt := st.chat_input("Ask the advisor, e.g. 'Can I take CS 450?'"):
    try:
        resp = httpx.post(
            f"{API_URL}/chat",
            json={"message": prompt, "thread_id": last["thread_id"] if last else None},
            timeout=120,
        )
        resp.raise_for_status()
        last = st.session_state["last"] = resp.json()
    except httpx.HTTPError as exc:
        st.error(f"API request failed: {exc}")

# State and tool calls hold the student's courses and grades, so the API only returns them
# in debug mode: run the API with `make api-debug` for this page.
state = (last or {}).get("state")
if last and state is None:
    st.warning("State and tool calls are hidden outside debug mode. Run `make api-debug`.")

with chat_col:
    for m in state["messages"] if state else []:
        st.chat_message(m["role"]).write(m["content"])

with debug_col:
    if last:
        if last["trace_url"]:
            st.link_button("Open Langfuse trace", last["trace_url"])
        st.caption(f"trace_id: {last['trace_id']}")
        st.subheader("Tool calls")
        st.json(last["tool_calls"] or [])
        st.subheader("Citations")
        st.json(last["citations"] or [])
        st.subheader("State")
        st.json({k: v for k, v in state.items() if k != "messages"} if state else {})

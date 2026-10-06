"""Dev-only terminal tracing of each orchestrator step (router -> agent -> merge).

Only imported by api.main when DEBUG=true (`make api-debug`), so production never loads it;
settings refuses DEBUG=true with ENV=prod. Nothing here changes request or response shapes.
"""

import json
import logging
import time
from typing import Any

from langgraph.graph.state import CompiledStateGraph

log = logging.getLogger("ssa.debug")

def configure_logging() -> None:
    if log.handlers:  # lifespan can run more than once per process (tests)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s  %(message)s", "%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

class TracedGraph:
    """Drop-in for the compiled graph: invoke() streams the run and logs each node's update."""

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def invoke(self, input: Any, config: dict[str, Any]) -> dict[str, Any]:
        thread = config["configurable"]["thread_id"][:8]
        log.debug("[%s] user: %s", thread, input["messages"][-1]["content"])
        state: dict[str, Any] = {}
        start = last = time.perf_counter()
        for mode, chunk in self._graph.stream(input, config, stream_mode=["updates", "values"]):
            if mode == "values":
                state = chunk
                continue
            for node, update in chunk.items():
                now = time.perf_counter()
                # Includes checkpoint writes since the previous step; Langfuse has exact timings.
                log.debug(
                    "[%s] %-16s +%5dms  %s",
                    thread,
                    node,
                    (now - last) * 1000,
                    json.dumps(update or {}, default=str)[:400],
                )
                last = now
        log.debug("[%s] done in %dms", thread, (time.perf_counter() - start) * 1000)
        return state

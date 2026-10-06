"""Create (or update) the gateway's per-agent API keys. Safe to run repeatedly."""

import httpx

from settings import get_settings

# One key per caller. Each key may only use the listed models, within its limits.
# max_budget is in US dollars; it starts to matter once a paid model (Claude) is added.
AGENT_KEYS = [
    {
        "key_alias": "router",
        "setting": "litellm_router_key",
        "models": ["local-llm"],
        "rpm_limit": 60,
        "max_budget": 5.0,
    },
]


def main() -> None:
    s = get_settings()
    admin = {"Authorization": f"Bearer {s.litellm_master_key.get_secret_value()}"}
    with httpx.Client(base_url=s.litellm_base_url, headers=admin, timeout=30) as client:
        for spec in AGENT_KEYS:
            key = getattr(s, spec["setting"]).get_secret_value()
            limits = {k: v for k, v in spec.items() if k not in ("key_alias", "setting")}
            # Update the key if it exists; create it if it doesn't.
            resp = client.post("/key/update", json={"key": key, **limits})
            if resp.status_code == 404:
                resp = client.post(
                    "/key/generate", json={"key": key, "key_alias": spec["key_alias"], **limits}
                )
            resp.raise_for_status()
            print(f"key ready: {spec['key_alias']}")


if __name__ == "__main__":
    main()

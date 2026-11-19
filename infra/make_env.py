"""Write .env from .env.example, with a fresh random value for every password and key.

`make up` runs this when there is no .env, so no two installs share a password and nothing
falls back to a value published in this repo. `make new-secrets` runs it with `--keep` to carry
over your own settings (OLLAMA_MODEL, LANGFUSE_PORT, ...) from the old file. Standard library
only: it runs before `uv sync`.

    python infra/make_env.py                    # .env.example -> .env
    python infra/make_env.py --keep .env.bak    # same, but non-secret values from .env.bak
    python infra/make_env.py --add-missing      # add secrets introduced since .env was made
"""

import argparse
import os
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hex(n: int) -> Callable[[], str]:
    return lambda: secrets.token_hex(n)


def _prefixed(prefix: str, n: int) -> Callable[[], str]:
    return lambda: prefix + secrets.token_hex(n)


# Hex keeps every value safe inside a URL (DATABASE_URL) and a YAML or shell command line.
SECRETS: dict[str, Callable[[], str]] = {
    "POSTGRES_PASSWORD": _hex(24),
    "LITELLM_MASTER_KEY": _prefixed("sk-", 24),
    "LITELLM_ROUTER_KEY": _prefixed("sk-", 24),
    "LITELLM_CATALOG_KEY": _prefixed("sk-", 24),
    "LITELLM_CAREER_KEY": _prefixed("sk-", 24),
    "LITELLM_UI_PASSWORD": _hex(12),
    "LANGFUSE_PUBLIC_KEY": _prefixed("pk-lf-", 16),
    "LANGFUSE_SECRET_KEY": _prefixed("sk-lf-", 24),
    "LANGFUSE_SALT": _hex(24),
    "LANGFUSE_ENCRYPTION_KEY": _hex(32),  # Langfuse requires exactly 64 hex characters
    "LANGFUSE_NEXTAUTH_SECRET": _hex(32),
    "LANGFUSE_INIT_USER_PASSWORD": _hex(12),
    "CLICKHOUSE_PASSWORD": _hex(24),
    "REDIS_PASSWORD": _hex(24),
    "MINIO_ROOT_PASSWORD": _hex(24),
}

LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def read_env(text: str) -> dict[str, str]:
    return {m[1]: m[2] for line in text.splitlines() if (m := LINE.match(line))}


def render(example: str, keep: dict[str, str] | None = None) -> str:
    """The example file with secrets generated, kept settings copied, and ${NAME} filled in."""
    values = {name: make() for name, make in SECRETS.items()}
    out = []
    for line in example.splitlines():
        m = LINE.match(line)
        if not m:
            out.append(line)
            continue
        name, value = m[1], m[2]
        if name in values:
            value = values[name]
        elif keep and name in keep and not REF.search(value):
            value = keep[name]  # derived values (DATABASE_URL) are always rebuilt
        # pydantic-settings does not expand ${...}, so resolve references here
        value = REF.sub(lambda r: values.get(r[1], r[0]), value)
        out.append(f"{name}={value}")
    return "\n".join(out) + "\n"


def add_missing(current: str) -> tuple[str, list[str]]:
    """Append a random value for every secret the file lacks; existing values are untouched.

    Only for a file made by this script: one from before random secrets (no POSTGRES_PASSWORD)
    is left alone, since new database passwords there would not match the existing database.
    That case needs `make new-secrets`.
    """
    have = read_env(current)
    if not have.get("POSTGRES_PASSWORD"):
        return current, []
    added = [name for name in SECRETS if not have.get(name)]
    if not added:
        return current, []
    lines = [
        line for line in current.splitlines() if not re.match(rf"^({'|'.join(added)})=$", line)
    ]
    lines += ["", "# Added by make up (new since this .env was created)"]
    lines += [f"{name}={SECRETS[name]()}" for name in added]
    return "\n".join(lines) + "\n", added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--example", type=Path, default=ROOT / ".env.example")
    parser.add_argument("--out", type=Path, default=ROOT / ".env")
    parser.add_argument("--keep", type=Path, help="copy non-secret settings from this file")
    parser.add_argument(
        "--add-missing", action="store_true", help="add new secrets to an existing .env"
    )
    args = parser.parse_args(argv)

    if args.add_missing:
        if not args.out.exists():
            return 0  # make creates it from scratch first
        text, added = add_missing(args.out.read_text())
        if added:
            args.out.write_text(text)
            print(f"added to {args.out}: {', '.join(added)}", file=sys.stderr)
        elif not read_env(text).get("POSTGRES_PASSWORD"):
            print(
                f"{args.out} is from before random passwords: run make new-secrets", file=sys.stderr
            )
        return 0
    if args.out.exists():
        sys.exit(f"{args.out} already exists; move it away first (make new-secrets does)")
    keep = read_env(args.keep.read_text()) if args.keep else None
    # Owner-only from the first byte: the file holds every password for the stack.
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(render(args.example.read_text(), keep))
    print(f"wrote {args.out} with new random passwords and keys", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Ollama runs the model, so its image is pinned by digest like the gateway's, and the AMD
override must stay on the same release as the base file."""

import re
from pathlib import Path

INFRA = Path(__file__).parents[2] / "infra"
PINNED = re.compile(r"image:\s*ollama/ollama:(\d+\.\d+\.\d+)(-rocm)?@sha256:[0-9a-f]{64}\s*$", re.M)


def _ollama_images(name: str) -> list[str]:
    text = (INFRA / name).read_text()
    return [line for line in text.splitlines() if "image:" in line and "ollama/ollama" in line]


def test_every_ollama_image_is_pinned_by_digest() -> None:
    for name in ("docker-compose.yml", "docker-compose.amd.yml"):
        images = _ollama_images(name)
        assert images, name
        for line in images:
            assert PINNED.search(line), f"{name}: {line.strip()} is not pinned"


def test_amd_override_uses_the_same_release() -> None:
    base = PINNED.search((INFRA / "docker-compose.yml").read_text())
    amd = PINNED.search((INFRA / "docker-compose.amd.yml").read_text())
    assert base and amd
    assert base.group(1) == amd.group(1)
    assert amd.group(2) == "-rocm"


DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_every_image_in_every_compose_file_is_pinned_by_digest() -> None:
    images = [
        (f.name, line.split("image:", 1)[1].strip())
        for f in sorted(INFRA.glob("docker-compose*.yml"))
        for line in f.read_text().splitlines()
        if line.strip().startswith("image:")
    ]
    assert len(images) >= 9
    unpinned = [f"{name}: {ref}" for name, ref in images if not DIGEST.search(ref)]
    assert not unpinned, unpinned


def test_langfuse_web_and_worker_run_the_same_release() -> None:
    text = (INFRA / "docker-compose.yml").read_text()
    versions = set(re.findall(r"image:\s*langfuse/langfuse(?:-worker)?:([\d.]+)@", text))
    assert len(versions) == 1, versions

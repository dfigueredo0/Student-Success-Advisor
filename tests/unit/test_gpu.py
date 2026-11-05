"""infra/gpu.py picks the compose override that gives Ollama this machine's GPU."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

INFRA = Path(__file__).parents[2] / "infra"


@pytest.fixture
def gpu() -> Any:
    spec = importlib.util.spec_from_file_location("gpu", INFRA / "gpu.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("system", "release", "tools", "kfd", "vendor"),
    [
        ("Darwin", "24.0", {"nvidia-smi"}, False, "cpu"),
        ("Linux", "6.10-arch1", set(), True, "amd"),
        ("Linux", "6.10-arch1", {"nvidia-smi", "nvidia-ctk"}, False, "nvidia"),
        ("Linux", "6.10-arch1", {"nvidia-smi"}, False, "cpu"),  # no container toolkit
        ("Linux", "5.15-microsoft-standard-WSL2", {"nvidia-smi"}, False, "nvidia"),
        ("Windows", "11", {"nvidia-smi"}, False, "nvidia"),
        ("Linux", "6.10-arch1", set(), False, "cpu"),
    ],
)
def test_detect(
    gpu: Any,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    release: str,
    tools: set[str],
    kfd: bool,
    vendor: str,
) -> None:
    monkeypatch.setattr(gpu.platform, "system", lambda: system)
    monkeypatch.setattr(gpu.platform, "release", lambda: release)
    monkeypatch.setattr(gpu.shutil, "which", lambda name: name if name in tools else None)
    monkeypatch.setattr(gpu.os.path, "exists", lambda path: kfd and path == "/dev/kfd")
    assert gpu.detect()[0] == vendor


@pytest.mark.parametrize("vendor", ["amd", "nvidia"])
def test_every_vendor_has_an_override(vendor: str) -> None:
    assert (INFRA / f"docker-compose.{vendor}.yml").is_file()

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


INTEL, AMD_PCI = {"0x8086"}, {"0x1002"}


@pytest.mark.parametrize(
    ("system", "release", "tools", "kfd", "drm", "vendor"),
    [
        ("Darwin", "24.0", {"nvidia-smi"}, False, set(), "cpu"),
        ("Linux", "6.10-arch1", set(), True, AMD_PCI, "amd"),
        ("Linux", "6.10-arch1", {"nvidia-smi", "nvidia-ctk"}, False, set(), "nvidia"),
        ("Linux", "6.10-arch1", {"nvidia-smi"}, False, set(), "cpu"),  # no container toolkit
        ("Linux", "5.15-microsoft-standard-WSL2", {"nvidia-smi"}, False, set(), "nvidia"),
        ("Windows", "11", {"nvidia-smi"}, False, set(), "nvidia"),
        ("Linux", "6.10-arch1", set(), False, set(), "cpu"),
        # Intel iGPU only, e.g. Core Ultra X7 358H (Arc B390) on CachyOS.
        ("Linux", "6.17-cachyos", set(), False, INTEL, "intel"),
        # Intel iGPU next to a dedicated card: the dedicated card wins.
        ("Linux", "6.10-arch1", {"nvidia-smi", "nvidia-ctk"}, False, INTEL, "nvidia"),
        ("Linux", "6.10-arch1", set(), True, INTEL | AMD_PCI, "amd"),
        # Docker Desktop can't pass /dev/dri through on Windows: only native Linux gets intel.
        ("Windows", "11", set(), False, INTEL, "cpu"),
    ],
)
def test_detect(
    gpu: Any,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    release: str,
    tools: set[str],
    kfd: bool,
    drm: set[str],
    vendor: str,
) -> None:
    monkeypatch.setattr(gpu.platform, "system", lambda: system)
    monkeypatch.setattr(gpu.platform, "release", lambda: release)
    monkeypatch.setattr(gpu.shutil, "which", lambda name: name if name in tools else None)
    monkeypatch.setattr(gpu.os.path, "exists", lambda path: kfd and path == "/dev/kfd")
    monkeypatch.setattr(gpu, "drm_vendors", lambda: drm)
    assert gpu.detect()[0] == vendor


def test_drm_vendors_reads_the_pci_id_of_each_card(
    gpu: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for card, vendor in [("card0", "0x8086\n"), ("card1", "0x1002\n")]:
        (tmp_path / card / "device").mkdir(parents=True)
        (tmp_path / card / "device" / "vendor").write_text(vendor)
    files = sorted(str(p) for p in tmp_path.glob("*/device/vendor"))
    monkeypatch.setattr(gpu.glob, "glob", lambda _: files)
    assert gpu.drm_vendors() == {"0x8086", "0x1002"}


def test_every_vendor_has_an_override(gpu: Any) -> None:
    for vendor in gpu.VENDORS:
        if vendor != "cpu":
            assert (INFRA / f"docker-compose.{vendor}.yml").is_file(), vendor

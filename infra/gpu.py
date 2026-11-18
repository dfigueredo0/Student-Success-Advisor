"""Pick the GPU vendor for Ollama: amd, nvidia, intel, or cpu.

`make up` layers infra/docker-compose.<vendor>.yml over the base file so Ollama runs on
whatever GPU this machine has. Prints that file's `-f` flag on stdout (nothing for cpu; read
by the Makefile) and the choice on stderr. `make up GPU=cpu|amd|nvidia|intel` passes the vendor
as an argument and skips detection. Standard library only: it runs before `uv sync`.
"""

import glob
import os
import platform
import shutil
import sys

VENDORS = ("cpu", "amd", "nvidia", "intel")
INTEL_PCI_ID = "0x8086"


def drm_vendors() -> set[str]:
    """PCI vendor IDs of the GPUs Linux exposes under /dev/dri."""
    ids = set()
    for path in glob.glob("/sys/class/drm/card[0-9]*/device/vendor"):
        try:
            with open(path) as f:
                ids.add(f.read().strip().lower())
        except OSError:
            pass
    return ids


def detect() -> tuple[str, str]:
    system = platform.system()
    if system == "Darwin":
        return "cpu", "Docker on macOS cannot give containers a GPU"
    if shutil.which("nvidia-smi"):
        # Docker Desktop (Windows, WSL) ships NVIDIA support; native Linux Docker needs the
        # container toolkit, or `up` fails with "could not select device driver nvidia".
        desktop = system == "Windows" or "microsoft" in platform.release().lower()
        if desktop or shutil.which("nvidia-ctk") or shutil.which("nvidia-container-runtime"):
            return "nvidia", "NVIDIA GPU"
        return "cpu", "NVIDIA GPU found, but nvidia-container-toolkit is not installed"
    if os.path.exists("/dev/kfd"):
        return "amd", "AMD GPU (ROCm /dev/kfd)"
    # Checked last: a laptop with an NVIDIA or AMD card often has an Intel iGPU as well, and
    # the dedicated card is the faster one.
    if system == "Linux" and INTEL_PCI_ID in drm_vendors():
        return "intel", "Intel GPU (Vulkan /dev/dri)"
    return "cpu", "no supported GPU found"


if __name__ == "__main__":
    vendor, reason = (sys.argv[1], "GPU= given") if len(sys.argv) > 1 else detect()
    if vendor not in VENDORS:
        sys.exit(f"GPU must be one of {', '.join(VENDORS)}, not {vendor!r}")
    print(f"ollama: {vendor} ({reason}); override with GPU={'|'.join(VENDORS)}", file=sys.stderr)
    if vendor != "cpu":
        print(f"-f infra/docker-compose.{vendor}.yml")

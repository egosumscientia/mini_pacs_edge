import os
import random
import time
from typing import Any, Dict

from receiver.config import load_config


class FaultError(RuntimeError):
    pass


def load_faults() -> Dict[str, Any]:
    config = load_config()
    return config.get("fault_injection", {})


def apply_faults(stage: str) -> None:
    faults = load_faults()
    if faults.get("reject_all"):
        raise FaultError("reject_all")

    io_delay_ms = int(faults.get("io_delay_ms", 0) or 0)
    if io_delay_ms > 0:
        time.sleep(io_delay_ms / 1000.0)

    rate = float(faults.get("random_fail_rate", 0.0) or 0.0)
    if rate > 0.0 and random.random() < rate:
        raise FaultError(f"random_fail_rate:{rate}")


def simulate_disk_full(path: str) -> None:
    faults = load_faults()
    if faults.get("disk_full"):
        raise OSError(f"disk_full:{path}")


def touch_file(path: str) -> None:
    simulate_disk_full(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "ab"):
        pass

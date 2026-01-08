import argparse
import sys
from typing import Dict

import yaml

from queue_store.queue_manager import get_counts, get_study_rows
from receiver.dicom_receiver import start_receiver


FAULT_PRESETS: Dict[str, Dict[str, float | bool | int]] = {
    "reject_all": {"reject_all": True},
    "disk_full": {"disk_full": True},
    "io_delay_ms": {"io_delay_ms": 500},
    "random_fail_rate": {"random_fail_rate": 0.3},
}


def _load_config() -> Dict:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config(config: Dict) -> None:
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def cmd_start(_: argparse.Namespace) -> None:
    start_receiver()


def cmd_status(args: argparse.Namespace) -> None:
    if args.study:
        rows = get_study_rows(args.study)
        if not rows:
            print("No records found")
            return
        for row in rows:
            print(row)
        return
    counts = get_counts()
    for state, count in counts.items():
        print(f"{state}: {count}")


def cmd_inject_fault(args: argparse.Namespace) -> None:
    name = args.name
    if name not in FAULT_PRESETS:
        raise SystemExit(f"Unknown fault: {name}")
    config = _load_config()
    faults = config.get("fault_injection", {})
    faults.update(FAULT_PRESETS[name])
    config["fault_injection"] = faults
    _save_config(config)
    print(f"Injected fault: {name}")


def cmd_clear_faults(_: argparse.Namespace) -> None:
    config = _load_config()
    config["fault_injection"] = {
        "reject_all": False,
        "disk_full": False,
        "io_delay_ms": 0,
        "random_fail_rate": 0.0,
    }
    _save_config(config)
    print("Faults cleared")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mini PACS Edge CLI")
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start")
    p_start.set_defaults(func=cmd_start)

    p_status = sub.add_parser("status")
    p_status.add_argument("--study", default=None)
    p_status.set_defaults(func=cmd_status)

    p_inject = sub.add_parser("inject-fault")
    p_inject.add_argument("name")
    p_inject.set_defaults(func=cmd_inject_fault)

    p_clear = sub.add_parser("clear-faults")
    p_clear.set_defaults(func=cmd_clear_faults)

    return parser


def main(argv: list[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(2)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])

#!/usr/bin/env python3
"""Deploy the complete, isolated Inky133 Style Evaluation environment."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
LOCAL_ROOT = REPOSITORY_ROOT / "output/experiments/inky133-style-evaluation"
DEFAULT_HOST = "inky133"
REMOTE_PROJECT = "inky133-slideshow"
CANONICAL_EXPERIMENT = "experiments/style_evaluation"
LEGACY_EXPERIMENT = "experiments/style-evaluation"
SERVICE_NAME = "inky133-style-evaluation.service"
UNIT_PATH = PACKAGE_ROOT / "systemd" / SERVICE_NAME
README_PATH = PACKAGE_ROOT / "README.md"
STYLE_KEYS = ("classic", "illustrated", "poster", "vintage", "watercolor")
SAFE_CHARACTERS = frozenset("-_.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
READY_MARKER = "Waiting for evaluation"
READY_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True, slots=True)
class DeployStep:
    key: str
    command: list[str]


def _safe_host(host: str) -> bool:
    return bool(host) and not host.startswith("-") and all(
        character in SAFE_CHARACTERS for character in host
    )


def validate_library(local_root: Path = LOCAL_ROOT) -> Path:
    root = local_root.expanduser().resolve(strict=True)
    expected = LOCAL_ROOT.resolve()
    if root != expected:
        raise ValueError(f"Style library must be exactly {expected}: {root}")
    missing = [key for key in STYLE_KEYS if not (root / "styles" / key).is_dir()]
    if missing:
        raise ValueError("Style library is incomplete; missing: " + ", ".join(missing))
    required = (
        root / "metadata.json",
        PACKAGE_ROOT / "pi" / "main.py",
        PACKAGE_ROOT / "pi" / "evaluator.py",
        PACKAGE_ROOT / "pi" / "display.py",
        README_PATH,
        UNIT_PATH,
    )
    absent = [str(path) for path in required if not path.is_file()]
    if absent:
        raise ValueError("Deploy file(s) missing: " + ", ".join(absent))
    return root


def _preflight_script(*, restart: bool) -> str:
    canonical = f'$HOME/{REMOTE_PROJECT}/{CANONICAL_EXPERIMENT}'
    legacy = f'$HOME/{REMOTE_PROJECT}/{LEGACY_EXPERIMENT}'
    restart_flag = "1" if restart else "0"
    return " ".join(
        (
            "set -eu;",
            f'canonical="{canonical}";',
            f'legacy="{legacy}";',
            'if [ -e "$legacy" ]; then',
            'if [ -e "$canonical" ]; then',
            'echo "ERROR: both style-evaluation and style_evaluation exist" >&2;',
            "else",
            'echo "ERROR: legacy style-evaluation directory exists" >&2;',
            "fi;",
            "exit 42;",
            "fi;",
            f'if systemctl is-active --quiet {SERVICE_NAME} && [ "{restart_flag}" != "1" ]; then',
            f'echo "ERROR: {SERVICE_NAME} is active; deploy with --restart" >&2;',
            "exit 43;",
            "fi;",
            'echo "Preflight OK: canonical style_evaluation only"',
        )
    )


def build_steps(
    *,
    host: str = DEFAULT_HOST,
    local_root: Path = LOCAL_ROOT,
    restart: bool = False,
) -> tuple[DeployStep, ...]:
    root = validate_library(local_root)
    if not _safe_host(host):
        raise ValueError(f"Invalid SSH host: {host!r}")

    remote = f"$HOME/{REMOTE_PROJECT}"
    canonical = f"{remote}/{CANONICAL_EXPERIMENT}"
    steps = [
        DeployStep("preflight", ["ssh", host, _preflight_script(restart=restart)]),
        DeployStep(
            "prepare",
            [
                "ssh",
                host,
                (
                    f'mkdir -p "{remote}/photos/styles" '
                    f'"{remote}/experiments/logs" "{canonical}"'
                ),
            ],
        ),
        DeployStep(
            "sync_app",
            [
                "rsync",
                "-av",
                "--exclude=.DS_Store",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                f"{PACKAGE_ROOT}/",
                f"{host}:~/{REMOTE_PROJECT}/{CANONICAL_EXPERIMENT}/",
            ],
        ),
        DeployStep(
            "sync_styles",
            [
                "rsync",
                "-av",
                "--exclude=.DS_Store",
                f"{root / 'styles'}/",
                f"{host}:~/{REMOTE_PROJECT}/photos/styles/",
            ],
        ),
        DeployStep(
            "sync_metadata",
            [
                "rsync",
                "-av",
                "--exclude=.DS_Store",
                str(root / "metadata.json"),
                f"{host}:~/{REMOTE_PROJECT}/photos/style-evaluation-metadata.json",
            ],
        ),
        DeployStep(
            "install_unit",
            [
                "ssh",
                host,
                (
                    "set -eu; "
                    f'sudo install -m 0644 "{canonical}/systemd/{SERVICE_NAME}" '
                    f'"/etc/systemd/system/{SERVICE_NAME}"; '
                    "sudo systemctl daemon-reload"
                ),
            ],
        ),
    ]
    if restart:
        steps.append(
            DeployStep(
                "restart",
                ["ssh", host, "sudo", "systemctl", "restart", SERVICE_NAME],
            )
        )
    return tuple(steps)


def build_commands(
    *,
    host: str = DEFAULT_HOST,
    local_root: Path = LOCAL_ROOT,
    restart: bool = False,
) -> tuple[list[str], ...]:
    """Compatibility helper used by tests and dry-run inspection."""
    return tuple(
        step.command
        for step in build_steps(host=host, local_root=local_root, restart=restart)
    )


def _run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def _service_active(host: str) -> bool:
    return _run(
        ["ssh", host, "systemctl", "is-active", "--quiet", SERVICE_NAME]
    ).returncode == 0


def _invocation_id(host: str) -> str:
    result = _run(
        [
            "ssh",
            host,
            "systemctl",
            "show",
            SERVICE_NAME,
            "--property=InvocationID",
            "--value",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip()


def wait_until_ready(
    host: str,
    *,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> bool:
    invocation_id = _invocation_id(host)
    if not invocation_id:
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _service_active(host):
            return False
        result = _run(
            [
                "ssh",
                host,
                "journalctl",
                f"_SYSTEMD_INVOCATION_ID={invocation_id}",
                "--no-pager",
                "-o",
                "cat",
            ],
            capture_output=True,
        )
        if result.returncode == 0 and READY_MARKER in result.stdout:
            return True
        time.sleep(2.0)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy the complete Inky133 Style Evaluation environment"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--restart",
        action="store_true",
        help=f"restart {SERVICE_NAME} and wait until it is ready",
    )
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        steps = build_steps(host=args.host, restart=args.restart)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("=== Inky133 Style Evaluation Deploy ===")
    print("Deploy started")
    if args.dry_run:
        for step in steps:
            print(f"[{step.key}] {shlex.join(step.command)}")
        print("Dry run completed; no remote changes made")
        return 0

    for step in steps:
        if step.key == "restart":
            print("Restarting service")
        result = _run(step.command)
        if result.returncode != 0:
            print(
                f"ERROR: deploy step {step.key!r} failed with {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode
        if step.key == "preflight":
            print("Preflight completed")
        elif step.key == "sync_metadata":
            print("Sync completed")
        elif step.key == "install_unit":
            print("Systemd unit installed")

    if not args.restart:
        print("Deploy completed; service was not restarted")
        return 0
    if not _service_active(args.host):
        print(f"ERROR: {SERVICE_NAME} is not active after restart", file=sys.stderr)
        return 1
    print("Service active")
    if not wait_until_ready(args.host):
        print(
            f"ERROR: {SERVICE_NAME} did not report {READY_MARKER!r} "
            f"within {READY_TIMEOUT_SECONDS:.0f}s",
            file=sys.stderr,
        )
        return 1
    print("Ready for evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

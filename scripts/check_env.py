#!/usr/bin/env python3
"""Check WorldQuant BRAIN project environment readiness.

Never prints credentials or their values — only whether keys exist.

Exit codes:
  0 = ready for login workflows
  1 = blockers found (wrong path / missing .env / missing credentials / missing core deps)
  2 = warnings only (e.g. wqbkit not importable -> workflow C unavailable)

Usage:
  python check_env.py --project-root /path/to/worldquantbrain
  python check_env.py                # falls back to $WQB_PROJECT_ROOT, then cwd
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REQUIRED_ENV_KEYS = ("WQB_USERNAME", "WQB_PASSWORD")
CORE_DEPENDENCIES = ("requests", "pandas", "dotenv")
OPTIONAL_DEPENDENCIES = ("wqbkit",)
ENTRY_POINTS = (
    "machine_lib.py",
    "alpha_machine.py",
    "alpha_explorer.py",
    "validate_operator_wqbkit.py",
    "config.py",
)
VENV_PYTHON_CANDIDATES = (
    Path(".venv") / "bin" / "python",
    Path(".venv") / "Scripts" / "python.exe",
)


def resolve_project_python(root: Path) -> Path:
    """Prefer the project venv interpreter; fall back to the current interpreter."""
    for candidate in VENV_PYTHON_CANDIDATES:
        candidate_path = root / candidate
        if candidate_path.is_file():
            return candidate_path
    return Path(sys.executable)


def check_dependencies_via(python: Path) -> dict[str, bool]:
    """Probe importability of core and optional deps using the given interpreter."""
    probe = (
        "import importlib.util, json; "
        "mods=['requests','pandas','dotenv','wqbkit']; "
        "print(json.dumps({m: bool(importlib.util.find_spec(m)) for m in mods}))"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return {name: bool(payload.get(name)) for name in payload}
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return {}


def parse_env_file(env_file: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, '#' comments, no shell expansion."""
    values: dict[str, str] = {}
    if not env_file.is_file():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help=(
            "WorldQuant BRAIN project root (default: $WQB_PROJECT_ROOT, "
            "then current directory)"
        ),
    )
    args = parser.parse_args(argv)

    root: Path = args.project_root
    if root is None:
        root = Path(os.environ.get("WQB_PROJECT_ROOT", "")).expanduser() or Path.cwd()
    blockers: list[str] = []
    warnings: list[str] = []

    def report(flag: str, message: str) -> None:
        print(f"[{flag}] {message}")

    # 1. Project root
    if not root.is_dir():
        report("BLOCKER", f"project_root not found: {root}")
        print(f"[SUMMARY] blockers={len(blockers) + 1} warnings={len(warnings)}")
        return 1
    report("OK", f"project_root={root}")

    # 2. Entry points
    missing_entries = [name for name in ENTRY_POINTS if not (root / name).is_file()]
    for name in missing_entries:
        blockers.append(f"missing entry file: {name}")

    # 3. .env and credentials
    env_file = root / ".env"
    if not env_file.is_file():
        blockers.append(f".env not found: {env_file} (copy .env.example and fill it)")
    else:
        report("OK", f".env found: {env_file}")
        env_values = parse_env_file(env_file)
        for key in REQUIRED_ENV_KEYS:
            value = env_values.get(key, "").strip()
            if value:
                report("OK", f"env key present: {key} (value hidden)")
            else:
                blockers.append(
                    f".env missing key: {key} (add {key}=<value> to {env_file})"
                )
        # DB keys matter only for workflow C
        for key in ("DB_ENABLE", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
            if not env_values.get(key, "").strip():
                warnings.append(f".env missing optional key: {key} (needed by workflow C)")

    # 4. Dependencies (via project venv when present, else current interpreter)
    python = resolve_project_python(root)
    if python != Path(sys.executable):
        report("OK", f"using project venv interpreter: {python}")
    dep_status = check_dependencies_via(python)
    if not dep_status:
        blockers.append("dependency probe failed (interpreter not runnable)")
    for dep in CORE_DEPENDENCIES:
        if dep_status.get(dep):
            report("OK", f"dependency importable: {dep} (via {python})")
        else:
            blockers.append(f"dependency not importable: {dep} (pip install {dep})")

    # 5. Optional dependencies
    for dep in OPTIONAL_DEPENDENCIES:
        if dep_status.get(dep):
            report("OK", f"dependency importable: {dep} (via {python})")
        else:
            warnings.append(
                f"dependency not importable: {dep} (workflow C / validate_operator_wqbkit.py unavailable)"
            )

    print(f"[SUMMARY] blockers={len(blockers)} warnings={len(warnings)}")
    for message in blockers:
        print(f"[BLOCKER] {message}")
    for message in warnings:
        print(f"[WARN] {message}")

    if blockers:
        return 1
    if warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

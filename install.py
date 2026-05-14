#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_NAME = "paper-chat-report"
HOST_SKILL_DIRS = {
    "codex": Path.home() / ".codex" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "agents": Path.home() / ".agents" / "skills",
}
SMOKE_TEST_SCRIPTS = (
    "init_paper_chat_report_artifacts.py",
    "extract_paper_chat_bundle.py",
    "validate_paper_chat_report.py",
    "enhance_report_format.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the paper-chat-report skill into Codex/Claude/Agents skill directories."
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(HOST_SKILL_DIRS),
        help="Install into a named host skill directory. Can be repeated.",
    )
    parser.add_argument(
        "--dest",
        help="Install into a custom skills directory. The skill will be copied into <dest>/paper-chat-report.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Replace an existing installation if present.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Skip pip dependency installation.",
    )
    parser.add_argument(
        "--with-docling",
        action="store_true",
        help="Also install optional docling dependencies.",
    )
    parser.add_argument(
        "--no-smoke-test",
        action="store_true",
        help="Skip post-install smoke tests.",
    )
    args = parser.parse_args()
    if args.dest and args.target:
        parser.error("--dest cannot be used together with --target")
    return args


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def source_skill_dir() -> Path:
    skill_dir = repo_root() / SKILL_NAME
    if not (skill_dir / "SKILL.md").exists():
        raise FileNotFoundError(f"Skill source not found: {skill_dir}")
    return skill_dir


def running_in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def resolve_target_skill_dirs(args: argparse.Namespace) -> list[Path]:
    if args.dest:
        return [Path(args.dest).expanduser().resolve()]
    if args.target:
        return [HOST_SKILL_DIRS[name] for name in args.target]
    detected = [path for path in HOST_SKILL_DIRS.values() if path.exists()]
    return detected or [HOST_SKILL_DIRS["codex"]]


def copy_skill(src: Path, skills_root: Path, upgrade: bool) -> Path:
    skills_root.mkdir(parents=True, exist_ok=True)
    dest = skills_root / SKILL_NAME
    if dest.exists():
        if not upgrade:
            raise FileExistsError(f"Destination already exists: {dest}. Re-run with --upgrade.")
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    return dest


def pip_install(requirements_file: Path) -> None:
    if not requirements_file.exists():
        return
    command = [sys.executable, "-m", "pip", "install"]
    if not running_in_venv():
        command.append("--user")
    command.extend(["-r", str(requirements_file)])
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed: {' '.join(command)}")


def smoke_test(installed_skill_dir: Path) -> None:
    scripts_dir = installed_skill_dir / "scripts"
    for script_name in SMOKE_TEST_SCRIPTS:
        command = [sys.executable, str(scripts_dir / script_name), "--help"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Smoke test failed for {script_name}: {stderr}")


def main() -> int:
    args = parse_args()
    src = source_skill_dir()
    skill_roots = resolve_target_skill_dirs(args)
    installed_paths = [copy_skill(src, skills_root, upgrade=args.upgrade) for skills_root in skill_roots]

    if not args.skip_pip:
        pip_install(src / "requirements.txt")
        if args.with_docling:
            pip_install(src / "requirements-optional.txt")

    if not args.no_smoke_test:
        for installed_path in installed_paths:
            smoke_test(installed_path)

    print("Installed paper-chat-report to:")
    for installed_path in installed_paths:
        print(f"- {installed_path}")
    if args.skip_pip:
        print("Skipped pip dependency installation.")
    elif args.with_docling:
        print("Installed core and optional docling dependencies.")
    else:
        print("Installed core dependencies.")
    print("Restart Codex / Claude to pick up the new skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

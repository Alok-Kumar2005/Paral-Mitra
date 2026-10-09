#!/usr/bin/env python3
"""Build script for Parali Mitra AWS Lambda deployment package.

Usage:
    python scripts/build_lambda.py

What it does:
  1. pip install runtime dependencies (manylinux2014_aarch64, cpython 3.12) into build/lambda/
  2. Copy src/ into build/lambda/src/
  3. Copy data/seed/ into build/lambda/data/seed/
  4. Remove __pycache__, *.pyc, and tests/ directories
  5. Print unzipped size and list top packages if > 240 MB (and exit 1)

The resulting build/lambda/ directory is a flat, self-contained deployment
package. Deploy it with:

    sam deploy \\
        --template-file infra/template.yaml \\
        --stack-name parali-mitra \\
        --region ap-south-1 \\
        --capabilities CAPABILITY_IAM \\
        --resolve-s3 \\
        --parameter-overrides \\
            TelegramBotToken='<token>' \\
            TelegramWebhookSecret='<secret>' \\
            DatabaseUrl='<neon-dsn>' \\
            FirmsMapKey='<firms-key>'

Note: --no-build is NOT needed and is not supported by older SAM CLI versions.
      sam deploy on a pre-built CodeUri directory never auto-runs sam build.

ALTERNATIVE: Docker-based build (for people with Docker installed):
    sam build --use-container --template-file infra/template.yaml
    sam deploy --template-file infra/template.yaml ...
    (This does NOT require running this script first.)

Cross-compilation note:
    --platform manylinux2014_aarch64 fetches the arm64 Linux wheels (matching
    AWS Lambda arm64). This works from any OS (Windows, macOS, Linux) without
    Docker. If a package has no pre-built arm64 wheel (--only-binary=:all:
    fails), remove it from requirements-lambda.txt and build inside a container.

Pip discovery:
    This script finds pip via: shutil.which('pip') -> shutil.which('pip3') ->
    sys.executable -m pip. This handles uv-managed venvs (no bundled pip),
    Conda envs, and standard venvs without change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_pip() -> list[str]:
    """Return a pip invocation that works in this environment.

    Search order:
      1. ``pip`` on PATH  (handles uv venvs, Conda, system installs)
      2. ``pip3`` on PATH
      3. ``sys.executable -m pip``  (standard venv fallback)

    Raises SystemExit if none are found.
    """
    for candidate in ("pip", "pip3"):
        found = shutil.which(candidate)
        if found:
            return [found]
    # Last resort: ask the current interpreter to run pip as a module
    return [sys.executable, "-m", "pip"]


# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build" / "lambda"
REQUIREMENTS = ROOT / "requirements-lambda.txt"
SRC_DIR = ROOT / "src"
DATA_SEED_DIR = ROOT / "data" / "seed"

MAX_SIZE_MB = 240


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess command, printing it first. Raises on failure."""
    print(f"\n>  {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)  # noqa: S603
    if result.returncode != 0:
        sys.exit(result.returncode)


def remove_pycache(directory: Path) -> None:
    """Recursively remove __pycache__ dirs and .pyc files."""
    for root, dirs, files in os.walk(directory, topdown=False):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(Path(root) / d, ignore_errors=True)
        for f in files:
            if f.endswith(".pyc") or f.endswith(".pyo"):
                (Path(root) / f).unlink(missing_ok=True)


def get_dir_size_mb(directory: Path) -> float:
    """Return total size of a directory tree in megabytes."""
    total = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def print_top_packages(build_dir: Path, n: int = 10) -> None:
    """Print the n largest top-level directories in the build directory."""
    entries = []
    for entry in build_dir.iterdir():
        if entry.is_dir():
            size_mb = get_dir_size_mb(entry)
            entries.append((size_mb, entry.name))
    entries.sort(reverse=True)
    print(f"\nTop {n} largest packages in {build_dir}:")
    for size_mb, name in entries[:n]:
        print(f"  {size_mb:7.1f} MB  {name}")


def main() -> None:
    print("=" * 60)
    print("Parali Mitra — Lambda build script")
    print("=" * 60)

    if not REQUIREMENTS.exists():
        print(f"ERROR: {REQUIREMENTS} not found.", file=sys.stderr)
        sys.exit(1)

    # ── Step 1: Clean and recreate build dir ──────────────────────────────────
    if BUILD_DIR.exists():
        print(f"\n[1/5] Cleaning existing build dir: {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    print(f"[1/5] Build directory created: {BUILD_DIR}")

    # ── Step 2: Install runtime dependencies (arm64 wheels) ──────────────────
    print("\n[2/5] Installing runtime dependencies (manylinux2014_aarch64)...")
    pip = _find_pip()
    print(f"  Using pip: {' '.join(pip)}")
    run(
        pip + [
            "install",
            "--platform", "manylinux2014_aarch64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
            "--target", str(BUILD_DIR),
            "-r", str(REQUIREMENTS),
            "--upgrade",
            "--quiet",
        ]
    )
    print("  [+] Dependencies installed.")

    # ── Step 3: Copy src/ ─────────────────────────────────────────────────────
    print("\n[3/5] Copying src/ ...")
    dest_src = BUILD_DIR / "src"
    if dest_src.exists():
        shutil.rmtree(dest_src)
    shutil.copytree(SRC_DIR, dest_src)
    print(f"  [+] Copied {SRC_DIR} -> {dest_src}")

    # ── Step 4: Copy data/seed/ and scripts/ ──────────────────────────────────
    print("\n[4/5] Copying data/seed/ and scripts/ ...")
    dest_data = BUILD_DIR / "data" / "seed"
    dest_data.parent.mkdir(parents=True, exist_ok=True)
    if dest_data.exists():
        shutil.rmtree(dest_data)
    shutil.copytree(DATA_SEED_DIR, dest_data)
    print(f"  [+] Copied {DATA_SEED_DIR} -> {dest_data}")

    dest_scripts = BUILD_DIR / "scripts"
    if dest_scripts.exists():
        shutil.rmtree(dest_scripts)
    scripts_src = Path(__file__).resolve().parent
    shutil.copytree(scripts_src, dest_scripts)
    print(f"  [+] Copied {scripts_src} -> {dest_scripts}")

    # ── Step 5: Cleanup ───────────────────────────────────────────────────────
    print("\n[5/5] Removing __pycache__, .pyc files, and tests/ ...")
    remove_pycache(BUILD_DIR)

    # Remove test directories that may have been included in src/ copy
    for tests_dir in BUILD_DIR.rglob("tests"):
        if tests_dir.is_dir():
            shutil.rmtree(tests_dir, ignore_errors=True)
            print(f"  Removed: {tests_dir.relative_to(BUILD_DIR)}")

    print("  [+] Cleanup complete.")

    # ── Size check ────────────────────────────────────────────────────────────
    total_mb = get_dir_size_mb(BUILD_DIR)
    print(f"\n{'=' * 60}")
    print(f"Unzipped build size: {total_mb:.1f} MB (limit: {MAX_SIZE_MB} MB)")

    if total_mb > MAX_SIZE_MB:
        print(
            f"\n[ERROR] Build size {total_mb:.1f} MB exceeds {MAX_SIZE_MB} MB limit!",
            file=sys.stderr,
        )
        print_top_packages(BUILD_DIR)
        print(
            "\nTo reduce size, consider:\n"
            "  - Removing large packages from requirements-lambda.txt\n"
            "  - Using Lambda Layers for heavy packages (boto3, etc.)\n"
            "  - Building with sam build --use-container (Docker)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n[OK] Build complete: {BUILD_DIR}")
    print(f"\nDeploy with (no --no-build flag needed — SAM does not auto-build pre-built CodeUri):")
    print(f"    sam deploy \\")
    print(f"        --template-file infra/template.yaml \\")
    print(f"        --stack-name parali-mitra \\")
    print(f"        --region ap-south-1 \\")
    print(f"        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \\")
    print(f"        --resolve-s3 \\")
    print(f"        --parameter-overrides \\")
    print(f"            TelegramBotToken='<token>' \\")
    print(f"            TelegramWebhookSecret='<secret>' \\")
    print(f"            'DatabaseUrl=<neon-dsn>' \\")
    print(f"            FirmsMapKey='<firms-key>'")
    print(f"\nAlternative (Docker): sam build --use-container --template-file infra/template.yaml")


if __name__ == "__main__":
    main()

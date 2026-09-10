#!/usr/bin/env bash
# Idempotent dev-environment bootstrap for IA_Trading on Linux (Cloud Agent / CI).
#
# The project targets a Windows MetaTrader 5 terminal, but its test suite and
# offline tooling run on Linux once a `MetaTrader5` stub satisfies the import.
#
# Dependencies are installed into the *user site-packages* (~/.local) rather than
# a virtualenv under the repo. With prebuilt environment builds, this install
# runs once to create the baseline snapshot and is skipped on later boots, and
# /workspace is re-checked-out from git on each boot. Installing outside
# /workspace keeps the interpreter's packages available regardless, so plain
# `python3 run_tests.py` works with no activation step.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Ubuntu's system Python is "externally managed"; --break-system-packages lets
# pip install into the per-user site. --user keeps it out of system dirs (no
# sudo) and persists in the snapshot at ~/.local.
PIP_FLAGS=(--user --break-system-packages --disable-pip-version-check)

# Install the Linux MetaTrader5 stub first. requirements.txt lists a bare
# `MetaTrader5` (Windows-only on PyPI); once the stub is installed, pip treats
# that requirement as satisfied and skips it.
python3 -m pip install "${PIP_FLAGS[@]}" -q "$ROOT/.cursor/mt5-stub"

# Remaining runtime dependencies (pandas, textblob, optuna).
python3 -m pip install "${PIP_FLAGS[@]}" -q -r "$ROOT/requirements.txt"

echo "IA_Trading dev environment ready. Run tests with: python3 run_tests.py"

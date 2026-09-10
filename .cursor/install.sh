#!/usr/bin/env bash
# Idempotent dev-environment bootstrap for IA_Trading on Linux (Cloud Agent / CI).
#
# The project targets a Windows MetaTrader 5 terminal, but its test suite and
# offline tooling run on Linux once a `MetaTrader5` stub satisfies the import.
#
# Dependencies are installed SYSTEM-WIDE (into /usr/local/lib) rather than a
# virtualenv under the repo or a per-user site. With prebuilt environment
# builds, /workspace is re-checked-out from git on each boot and this install is
# skipped on later boots, so anything under /workspace or tied to $HOME is
# unreliable. A system-wide install lives on the base disk snapshot and is
# importable by plain `python3` for any user, so `python3 run_tests.py` just
# works with no activation step.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

# Ubuntu's system Python is "externally managed"; --break-system-packages lets
# pip install into the system site (/usr/local/lib/pythonX.Y/dist-packages).
PIP_FLAGS=(--break-system-packages --disable-pip-version-check)

# Install the Linux MetaTrader5 stub first. requirements.txt lists a bare
# `MetaTrader5` (Windows-only on PyPI); once the stub is installed, pip treats
# that requirement as satisfied and skips it.
$SUDO python3 -m pip install "${PIP_FLAGS[@]}" -q "$ROOT/.cursor/mt5-stub"

# Remaining runtime dependencies (pandas, textblob, optuna).
$SUDO python3 -m pip install "${PIP_FLAGS[@]}" -q -r "$ROOT/requirements.txt"

# Fail fast if anything the project imports at load time is missing, so a broken
# install surfaces here instead of as import errors when running the app/tests.
python3 - <<'PY'
import MetaTrader5, pandas, textblob, optuna  # noqa: F401
print("IA_Trading deps OK:", "pandas", pandas.__version__, "| MetaTrader5", MetaTrader5.version())
PY

echo "IA_Trading dev environment ready. Run tests with: python3 run_tests.py"

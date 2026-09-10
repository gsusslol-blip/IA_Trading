#!/usr/bin/env bash
# Idempotent dev-environment bootstrap for IA_Trading on Linux (Cloud Agent / CI).
#
# The project targets a Windows MetaTrader 5 terminal, but its test suite and
# offline tooling run fine on Linux once a `MetaTrader5` stub satisfies the
# import. This script provisions a local virtualenv with that stub plus the
# real runtime deps (pandas, textblob, optuna).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Ensure venv support (ensurepip ships in the python3-venv package on Debian/Ubuntu).
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  sudo apt-get update -qq
  sudo apt-get install -y -qq "python${PYVER}-venv"
fi

# Create the virtualenv on first run; reuse it afterwards.
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip -q

# Install the Linux MetaTrader5 stub first. requirements.txt lists a bare
# `MetaTrader5` (Windows-only on PyPI); once the stub is installed, pip treats
# that requirement as satisfied and skips it.
python -m pip install -q "$ROOT/.cursor/mt5-stub"

# Remaining runtime dependencies.
python -m pip install -q -r "$ROOT/requirements.txt"

echo "IA_Trading dev environment ready. Activate with: source .venv/bin/activate"

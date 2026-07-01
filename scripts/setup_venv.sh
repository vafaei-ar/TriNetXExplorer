#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${1:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

echo ""
echo "Virtual environment ready: ${VENV_DIR}"
echo "Activate it with: source ${VENV_DIR}/bin/activate"
echo "Run dashboard with: streamlit run dashboard/app.py"

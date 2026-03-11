#!/usr/bin/env bash
set -e

# Run from workspace root (parent of .devcontainer)
cd "$(dirname "$0")/.."

echo "==> Upgrading pip..."
pip install --upgrade pip

if [[ -f requirements.txt ]]; then
  echo "==> Installing requirements..."
  pip install -r requirements.txt
fi

echo "==> Installing Playwright Chromium..."
python -m playwright install chromium || true

echo "==> Post-create done."

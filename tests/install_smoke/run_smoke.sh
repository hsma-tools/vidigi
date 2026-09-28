#!/usr/bin/env bash
# Install vidigi into an empty virtualenv and run smoke_model.py against it.
#
# Usage: tests/install_smoke/run_smoke.sh <pip install arguments...>
#   e.g. tests/install_smoke/run_smoke.sh vidigi
#        tests/install_smoke/run_smoke.sh vidigi==2.0.0
#        tests/install_smoke/run_smoke.sh dist/vidigi-2.0.0-py3-none-any.whl
#
# The script runs from a temporary directory, so the checkout is never on
# sys.path. Set INSTALL_ATTEMPTS (default 1) to retry the install every 30s, for
# a release that PyPI's index may not be serving yet. EXPECTED_VERSION, if set,
# is checked by smoke_model.py.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work" || true' EXIT

python -m venv "$work/venv"
if [ -x "$work/venv/Scripts/python.exe" ]; then
    py="$work/venv/Scripts/python.exe"
else
    py="$work/venv/bin/python"
fi

"$py" -m pip install --upgrade pip

attempts="${INSTALL_ATTEMPTS:-1}"
for ((attempt = 1; ; attempt++)); do
    "$py" -m pip install --no-cache-dir "$@" && break
    [ "$attempt" -ge "$attempts" ] && exit 1
    echo "Install attempt $attempt of $attempts failed; retrying in 30s"
    sleep 30
done

"$py" -m pip check

cp "$here/smoke_model.py" "$work/smoke_model.py"
cd "$work"
"$py" smoke_model.py

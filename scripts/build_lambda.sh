#!/usr/bin/env bash
# Builds build/lambda: app code + runtime deps for Lambda (linux/arm64, py3.12). boto3 comes from the runtime.
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf build/lambda
mkdir -p build/lambda

uv export --no-default-groups --no-hashes --no-emit-project --no-header -o build/requirements.txt >/dev/null
uv pip install --quiet --no-compile --target build/lambda \
  --python-platform aarch64-manylinux2014 --python-version 3.12 \
  -r build/requirements.txt

cp -r onboarding build/lambda/onboarding
find build/lambda -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "built build/lambda ($(du -sh build/lambda | cut -f1))"

#!/usr/bin/env bash
set -euo pipefail

# Build Lambda deployment packages locally.
# Usage: ./scripts/deploy.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Cleaning previous build"
rm -rf "$PROJECT_DIR/dist"
mkdir -p "$PROJECT_DIR/dist"

# Build ingest package
echo "==> Building ingest package"
mkdir -p "$PROJECT_DIR/dist/ingest"
pip install -r "$PROJECT_DIR/requirements.txt" -t "$PROJECT_DIR/dist/ingest/" --quiet
cp "$PROJECT_DIR/src/ingest.py" "$PROJECT_DIR/dist/ingest/"
cd "$PROJECT_DIR/dist/ingest"
zip -r "$PROJECT_DIR/dist/ingest.zip" . -q
cd "$PROJECT_DIR"

# Build query package
echo "==> Building query package"
mkdir -p "$PROJECT_DIR/dist/query"
pip install -r "$PROJECT_DIR/requirements.txt" -t "$PROJECT_DIR/dist/query/" --quiet
cp "$PROJECT_DIR/src/query.py" "$PROJECT_DIR/dist/query/"
cd "$PROJECT_DIR/dist/query"
zip -r "$PROJECT_DIR/dist/query.zip" . -q
cd "$PROJECT_DIR"

INGEST_SIZE=$(du -h "$PROJECT_DIR/dist/ingest.zip" | cut -f1)
QUERY_SIZE=$(du -h "$PROJECT_DIR/dist/query.zip" | cut -f1)

echo "==> Done"
echo "    dist/ingest.zip ($INGEST_SIZE)"
echo "    dist/query.zip ($QUERY_SIZE)"
echo ""
echo "Next steps:"
echo "  cd terraform && terraform plan -out=tfplan"
echo "  terraform apply tfplan"

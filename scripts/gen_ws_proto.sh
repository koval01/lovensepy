#!/usr/bin/env bash
# Regenerate Python + TypeScript stubs for the control-panel /ws protobuf schema.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROTO_DIR="$ROOT/lovensepy/services/http_api/proto"
PY_OUT="$ROOT/lovensepy/services/http_api"
TS_OUT="$ROOT/frontend/src/lib"

PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON:-python3}"
fi

"$PYTHON" -m grpc_tools.protoc \
  -I"$PROTO_DIR" \
  --python_out="$PY_OUT" \
  "$PROTO_DIR/ws.proto"

cd "$ROOT/frontend"
npx protoc \
  --plugin=protoc-gen-es=./node_modules/.bin/protoc-gen-es \
  --es_out="$TS_OUT" \
  --es_opt=target=ts \
  -I"$PROTO_DIR" \
  "$PROTO_DIR/ws.proto"

echo "Regenerated ws_pb2.py and ws_pb.ts"

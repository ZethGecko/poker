#!/usr/bin/env bash
# Arranca la mesa de poker y muestra las direcciones para que se unan los amigos.
set -e
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8000}}"
HOST="${2:-${HOST:-0.0.0.0}}"

echo ""
echo "  Mesa de poker · solo Python 3, sin dependencias"
echo "  ----------------------------------------------------"
exec python3 -m server.app --host "$HOST" --port "$PORT"

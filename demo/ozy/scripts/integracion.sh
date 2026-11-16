#!/usr/bin/env bash
# Prueba de integración de Ozy con users, channels y messages en Docker Compose.
#
# Levanta demo/docker-compose.test.yaml (entorno efímero, sin volúmenes), corre
# tests/integration con pytest y destruye el entorno, pase o falle.
#
#   ozy/scripts/integracion.sh              # desde demo/ (o desde cualquier lugar)
#   KEEP=1 ozy/scripts/integracion.sh       # deja el entorno arriba para revisarlo
#   PYTHON=.venv/bin/python ozy/scripts/integracion.sh
set -euo pipefail

OZY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$(dirname "$OZY_DIR")"
PYTHON="${PYTHON:-python3}"
compose() { docker compose -f "$DEMO_DIR/docker-compose.test.yaml" -p ozy-integracion "$@"; }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- La prueba falló: últimos logs de los servicios ---"
    compose logs --tail 60 users channels messages ozy || true
  fi
  if [ "${KEEP:-0}" = "1" ]; then
    echo "Entorno arriba (KEEP=1). Para bajarlo:"
    echo "  docker compose -f $DEMO_DIR/docker-compose.test.yaml -p ozy-integracion down -v"
  else
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

echo "--- Levantando users, channels, messages, ozy y rabbitmq ---"
compose up -d --build --wait --wait-timeout 180

echo "--- Corriendo la prueba de integración ---"
cd "$OZY_DIR"
"$PYTHON" -m pytest -m integration tests/integration -v "$@"

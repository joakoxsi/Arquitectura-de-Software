#!/usr/bin/env bash
# Evidencia 1: flujo integrado de Ozy contra el chat base desplegado en el clúster.
#
# Uso (desde la raíz del repo, con kubectl apuntando al clúster del curso):
#   NS=grupo-ozy CORE_NS=servicios-base demo/ozy/k8s/evidencia/flujo-integrado.sh
#
# Deja todo en demo/ozy/k8s/evidencia/salida/<fecha>-flujo/ :
#   00-estado.txt   recursos de Ozy (deploy, pods, hpa, probes) y del core (solo lectura)
#   01-e2e.log      salida del Job ozy-e2e (cada paso con [OK])
#   02-ozy.log      logs de Ozy: consumo del broker o sincronización por la API de messages
#   resumen.txt     resultado final
set -uo pipefail

NS="${NS:?define NS con el namespace del grupo}"
CORE_NS="${CORE_NS:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"
K8S="$(dirname "$DIR")"
OUT="$DIR/salida/$(date +%Y%m%d-%H%M%S)-flujo"
mkdir -p "$OUT"
k() { kubectl -n "$NS" "$@"; }
section() { printf '\n===== %s — %s =====\n' "$1" "$(date -Is)"; }

{
  section "Contexto"
  kubectl config current-context
  kubectl version 2>/dev/null | head -2
  section "Recursos de Ozy en $NS"
  k get deploy,sts,svc,hpa -l app.kubernetes.io/name=ozy -o wide
  section "Pods de Ozy"
  k get pods -l app.kubernetes.io/name=ozy -o wide
  section "Imagen desplegada"
  k get deploy ozy -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
  section "Probes configuradas"
  k get deploy ozy -o jsonpath='{range .spec.template.spec.containers[0]}startup:   {.startupProbe.httpGet.path}{"\n"}liveness:  {.livenessProbe.httpGet.path}{"\n"}readiness: {.readinessProbe.httpGet.path}{"\n"}{end}'
  section "Probes respondiendo (desde un pod de Ozy)"
  POD=$(k get pods -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}')
  k exec "$POD" -- python -c "import urllib.request as u;[print(p, u.urlopen('http://localhost:8000'+p).read().decode()) for p in ('/health/live','/health/ready')]"
  if [ -n "$CORE_NS" ]; then
    section "Chat base en $CORE_NS (solo lectura, no se modifica)"
    # Solo deployments (sin Services ni puertos): las URLs internas no van a la evidencia.
    kubectl -n "$CORE_NS" get deploy 2>&1 || echo "(sin permiso de lectura sobre $CORE_NS)"
  fi
} > "$OUT/00-estado.txt" 2>&1
echo "Estado guardado en $OUT/00-estado.txt"

echo "Lanzando Job ozy-e2e…"
k delete job ozy-e2e --ignore-not-found --wait=true >/dev/null
kubectl apply -k "$K8S/pruebas" -l app.kubernetes.io/component=e2e
# Espera a que termine (completo o fallido).
for _ in $(seq 1 60); do
  done_=$(k get job ozy-e2e -o jsonpath='{.status.succeeded}{.status.failed}')
  [ -n "$done_" ] && break
  sleep 5
done
k logs job/ozy-e2e > "$OUT/01-e2e.log" 2>&1
k logs -l app.kubernetes.io/component=api --prefix --tail=200 > "$OUT/02-ozy.log" 2>&1

{
  section "Resultado"
  k get job ozy-e2e -o wide
  if [ "$(k get job ozy-e2e -o jsonpath='{.status.succeeded}')" = "1" ]; then
    echo "FLUJO INTEGRADO OK"
  else
    echo "FLUJO INTEGRADO FALLÓ — ver 01-e2e.log"
  fi
  section "Últimas líneas del e2e"
  tail -15 "$OUT/01-e2e.log"
  section "Cómo recibe Ozy los mensajes del chat base"
  # Con broker: "Consuming chat.message.created…". Sin broker: "Syncing messages…"
  # y "Synced N new message(s)" en la réplica que tiene el lease.
  grep -hE "Consuming|Syncing messages|Synced [0-9]+ new" "$OUT/02-ozy.log" | sort | uniq -c
} | tee "$OUT/resumen.txt"

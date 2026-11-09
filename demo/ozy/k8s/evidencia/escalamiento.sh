#!/usr/bin/env bash
# Evidencia 2: escalamiento automático (HPA) de Ozy bajo carga y vuelta al mínimo.
#
# Uso (desde la raíz del repo, con kubectl apuntando al clúster del curso):
#   NS=grupo-ozy demo/ozy/k8s/evidencia/escalamiento.sh
# Variables opcionales: COOLDOWN (s de observación tras la carga, def. 300).
#
# Deja todo en demo/ozy/k8s/evidencia/salida/<fecha>-escala/ :
#   00-inicial.txt   HPA, pods y consumo antes de la carga
#   serie.csv        cada 15 s: réplicas deseadas/actuales/listas y CPU promedio
#   01-watch.log     lo mismo, legible, más `kubectl top pods`
#   02-carga.log     salida de los generadores (req/s, latencias, reparto por réplica)
#   03-hpa.txt       describe del HPA con sus eventos (SuccessfulRescale)
#   resumen.txt      mínimo y máximo de réplicas observados
set -uo pipefail

NS="${NS:?define NS con el namespace del grupo}"
COOLDOWN="${COOLDOWN:-300}"
DIR="$(cd "$(dirname "$0")" && pwd)"
K8S="$(dirname "$DIR")"
OUT="$DIR/salida/$(date +%Y%m%d-%H%M%S)-escala"
mkdir -p "$OUT"
k() { kubectl -n "$NS" "$@"; }

{
  echo "== $(date -Is) estado inicial"
  k get hpa ozy
  k get pods -l app.kubernetes.io/component=api -o wide
  k top pods -l app.kubernetes.io/component=api 2>&1
} > "$OUT/00-inicial.txt" 2>&1
cat "$OUT/00-inicial.txt"

echo "timestamp,fase,deseadas,actuales,listas,cpu_promedio_pct" > "$OUT/serie.csv"
sample() {  # $1 = fase
  local ts desired current ready cpu
  ts=$(date -Is)
  desired=$(k get hpa ozy -o jsonpath='{.status.desiredReplicas}')
  current=$(k get hpa ozy -o jsonpath='{.status.currentReplicas}')
  ready=$(k get deploy ozy -o jsonpath='{.status.readyReplicas}')
  cpu=$(k get hpa ozy -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}')
  echo "$ts,$1,${desired:-0},${current:-0},${ready:-0},${cpu:-}" >> "$OUT/serie.csv"
  {
    echo "== $ts [$1] deseadas=${desired:-?} actuales=${current:-?} listas=${ready:-?} cpu=${cpu:-?}%"
    k top pods -l app.kubernetes.io/component=api --no-headers 2>/dev/null
  } >> "$OUT/01-watch.log"
  echo "$ts [$1] réplicas ${current:-?}->${desired:-?} (listas ${ready:-?}) cpu ${cpu:-?}%"
}

echo "Lanzando Job ozy-carga…"
k delete job ozy-carga --ignore-not-found --wait=true >/dev/null
kubectl apply -k "$K8S/pruebas" -l app.kubernetes.io/component=carga

# Observa mientras dura la carga.
while true; do
  sample carga
  active=$(k get job ozy-carga -o jsonpath='{.status.active}')
  finished=$(k get job ozy-carga -o jsonpath='{.status.succeeded}{.status.failed}')
  if [ -z "$active" ] && [ -n "$finished" ]; then break; fi
  sleep 15
done
k logs job/ozy-carga --all-pods=true --prefix > "$OUT/02-carga.log" 2>&1 \
  || k logs -l app.kubernetes.io/component=carga --prefix --tail=-1 > "$OUT/02-carga.log" 2>&1

# Observa la bajada (estabilización de 120 s + 1 pod cada 30 s).
end=$((SECONDS + COOLDOWN))
while [ $SECONDS -lt $end ]; do
  sample enfriamiento
  sleep 15
done

k describe hpa ozy > "$OUT/03-hpa.txt" 2>&1
{
  echo "== Resumen $(date -Is)"
  awk -F, 'NR>1 && $4!="" {if(min==""||$4<min)min=$4; if($4>max)max=$4}
           END {print "réplicas mínimas observadas: " min "\nréplicas máximas observadas: " max}' "$OUT/serie.csv"
  awk -F, 'NR>1 && $6!="" {if($6>m)m=$6} END {print "CPU promedio máxima: " m "% (objetivo 60%)"}' "$OUT/serie.csv"
  echo
  echo "Eventos del HPA:"
  grep -E "SuccessfulRescale|New size" "$OUT/03-hpa.txt" || echo "(ver 03-hpa.txt)"
  echo
  echo "Reparto de respuestas por réplica (generadores de carga):"
  grep -h "Fin." "$OUT/02-carga.log"
} | tee "$OUT/resumen.txt"

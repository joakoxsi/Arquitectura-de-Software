"""Generador de carga para demostrar el autoscaling (HPA) de Ozy.

Solo llama endpoints de lectura de Ozy (glosario) para que la carga caiga sobre
Ozy y su MongoDB propia, sin crear datos en el chat base ni publicar eventos en
el broker compartido del curso.

Uso:
    OZY_URL=http://ozy:8000 DURATION=300 CONCURRENCY=24 python scripts/carga.py

Cada INTERVAL segundos imprime: peticiones/s, latencia p50/p95, errores y cuántas
respuestas dio cada réplica (cabecera X-Ozy-Instance). Solo biblioteca estándar.
"""
import os
import random
import sys
import threading
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

OZY = os.environ.get("OZY_URL", "http://localhost:8004").rstrip("/")
DURATION = int(os.environ.get("DURATION", "300"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "24"))
INTERVAL = int(os.environ.get("INTERVAL", "15"))
TERMS = ["PR", "API", "KPI", "Pipeline", "SLA", "Lead", "Backlog", "Devengado"]
PATHS = (["/api/v1/glossary"] * 3 + [f"/api/v1/glossary/{t}" for t in TERMS]
         + ["/api/v1/glossary?ambito=software", "/api/v1/glossary?estado=validado"])

lock = threading.Lock()
latencies: list[float] = []
errors = Counter()
by_instance = Counter()
total_by_instance = Counter()
stop = threading.Event()


def worker() -> None:
    while not stop.is_set():
        path = random.choice(PATHS)
        start = time.perf_counter()
        instance, error = None, None
        try:
            with urlopen(OZY + path, timeout=10) as response:
                response.read()
                instance = response.headers.get("X-Ozy-Instance")
        except HTTPError as exc:
            error = str(exc.code)
            instance = exc.headers.get("X-Ozy-Instance")
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            error = exc.__class__.__name__
        elapsed = time.perf_counter() - start
        with lock:
            latencies.append(elapsed)
            if error:
                errors[error] += 1
            if instance:
                by_instance[instance] += 1
                total_by_instance[instance] += 1


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


def report(elapsed: float) -> None:
    with lock:
        window = latencies[:]
        latencies.clear()
        errs = dict(errors)
        errors.clear()
        pods = dict(by_instance)
        by_instance.clear()
    rate = len(window) / INTERVAL
    print(f"[t={elapsed:5.0f}s] {rate:7.1f} req/s | p50 {percentile(window, .5)*1000:6.1f} ms"
          f" | p95 {percentile(window, .95)*1000:6.1f} ms | errores {errs or 0}"
          f" | réplicas activas {len(pods)}: {pods}", flush=True)


def main() -> None:
    print(f"Carga sobre {OZY} durante {DURATION}s con {CONCURRENCY} hilos", flush=True)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(CONCURRENCY)]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    while (elapsed := time.monotonic() - started) < DURATION:
        time.sleep(min(INTERVAL, DURATION - elapsed))
        report(time.monotonic() - started)
    stop.set()
    for thread in threads:
        thread.join(timeout=15)
    print(f"Fin. Respuestas por réplica en toda la prueba: {dict(total_by_instance)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

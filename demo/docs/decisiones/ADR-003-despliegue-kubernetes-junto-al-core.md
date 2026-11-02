# ADR-003: Desplegar Ozy en Kubernetes junto al chat base, sin modificarlo

- **Estado:** aceptada
- **Fecha:** 2026-11-01
- **Contexto de origen:** entrega de despliegue en el clúster común del curso

## Contexto

El curso despliega el chat base (`users`, `channels`, `messages` y su broker) en
un clúster común. Cada grupo debe desplegar su microservicio sobre esa instancia,
idealmente con integración continua, con readiness/liveness probes y autoscaling,
**sin redesplegar ni modificar el core**.

En local (compose) Ozy dependía de cosas que en el clúster no controlamos: el
broker lo levantábamos nosotros (ADR-001) y los servicios base los corregíamos
nosotros (ADR-002). En el clúster el core es del curso y es compartido por todos
los grupos.

## Decisión

1. **Ozy vive en el namespace del grupo** con todo lo que le pertenece:
   Deployment, Service, HPA, PDB, ConfigMap, Secret y **su propia MongoDB**
   (StatefulSet con PVC, accesible solo desde los pods de Ozy por NetworkPolicy).
   Se aplica con kustomize (`demo/ozy/k8s/overlays/curso`), que solo contiene
   recursos de Ozy: el pipeline no puede tocar el core aunque quisiera.
2. **Integración solo por interfaces públicas del core.** En el clúster,
   `messages` no tiene `RABBITMQ_URL` (no publica eventos) y no podemos
   modificarlo. Por eso Ozy incorpora un **sincronizador por API** (*polling
   consumer*, detalle en [ADR-004](ADR-004-ingesta-por-api-y-broker-propio.md)): cada 5 s lee `GET /api/v1/channels` y
   `GET /api/v1/channels/{id}/messages`, pasa cada mensaje por la misma capa
   anticorrupción y lo copia al mismo read-model. Una sola réplica sincroniza a
   la vez gracias a un *lease* en la base propia, para no multiplicar la carga
   sobre el core compartido. `POST …/translation?channel_id=` sincroniza un canal
   al instante. El consumidor RabbitMQ se mantiene: se usa si hay `RABBITMQ_URL`
   (compose local, `CONSUME_MESSAGE_EVENTS=true`). Sus eventos propios los publica
   en **un RabbitMQ propio** del namespace (`ozy-rabbitmq`). `users` se consulta
   por `GET /api/v1/users/{id}`. Las direcciones del core **no se versionan**: el
   CI arma `core.env` desde secrets de GitHub, y las credenciales del broker van
   al Secret `ozy-secrets`.
3. **Probes con significado distinto:**
   - *startup* cubre la espera a MongoDB al arrancar (índices + seed);
   - *liveness* (`/health/live`) solo falla si el proceso o el hilo de ingesta
     (sincronizador o consumidor) murieron, porque reiniciar no arregla dependencias caídas;
   - *readiness* (`/health/ready`) falla si su MongoDB no responde. RabbitMQ no
     se exige, porque sin broker la API sigue funcionando.
4. **Autoscaling horizontal por CPU** (HPA 2–4, objetivo 60 %, dimensionado
   para caber en la `ResourceQuota` del grupo junto al broker y con la carga
   corriendo). La API ya era *stateless*: las réplicas comparten la MongoDB
   propia, el *lease* evita que sincronicen varias a la vez y el upsert del
   read-model es idempotente.
5. **CI/CD con GitHub Actions** (`.github/workflows/ozy-k8s.yml`): tests →
   imagen en GHCR etiquetada con el commit → `kubectl apply` → rollout → prueba
   integrada dentro del clúster. La evidencia queda como artifact.
6. **Las pruebas corren como Jobs dentro del clúster** usando la misma imagen de
   Ozy (trae `scripts/e2e.py` y `scripts/carga.py`): no hay que exponer servicios
   del core hacia afuera ni depender de otras imágenes.
7. **La carga para el HPA solo lee el glosario de Ozy**, para no crear datos en
   el core compartido ni cargarlo con peticiones.

## Consecuencias

- Cambios de código acotados a Ozy: endpoints `/health/live` y `/health/ready`,
  reintento de conexión a MongoDB al arrancar, cabecera `X-Ozy-Instance`, y un
  Dockerfile de producción (sin `--reload`, usuario no root). El compose local
  conserva el `--reload` con `command:`.
- Los eventos que emite Ozy se guardan en su base (`published_events`): con varias
  réplicas, `GET /api/v1/events` responde lo mismo desde cualquiera. Sin broker en
  el core, nadie más los recibe por ahora; el día que exista, se configura
  `OZY_RABBITMQ_URL` y Ozy los publica sin cambiar código.
- En el clúster, un mensaje nuevo tarda hasta 5 s en llegar al read-model, y cada
  ciclo relee todos los canales (la API de `messages` no filtra por fecha).
- La MongoDB propia es de una sola réplica: la capacidad escala en la API, no en
  el estado. Si fuera el cuello de botella, el siguiente paso sería un replica set.
- Si el curso cambia nombres de servicios o del exchange, solo se ajustan
  `core.env`, el Secret o la capa anticorrupción (`app/acl.py`).
- **Verificado en el clúster:** el kubeconfig fija el namespace del grupo, la
  cuota permite el peor caso con margen, y `messages` en `servicios-base` solo
  tiene `MONGODB_URL`, `USERS_URL` y `CHANNELS_URL` (sin broker).

# Arquitectura-de-Software
Repositorio creado para realizar las tarea del ramo del mismo nombre de la USM, donde se desarollara un sistema basado en las buenas practicas de esta area del desarrollo de software

## Trabajo final: microservicio Ozy

Sistema de chat en microservicios (Python + FastAPI + MongoDB + RabbitMQ). El
microservicio asignado es **Ozy**, que traduce la jerga técnica de los mensajes a
lenguaje simple y mantiene un glosario con ámbito.

| Qué | Dónde |
|---|---|
| Documentación de Ozy (API, eventos, errores, versionamiento, flujo con curl) | [demo/ozy/README.md](demo/ozy/README.md) |
| Código de Ozy y tests | [demo/ozy/](demo/ozy/) |
| API Gateway GraphQL (queries, mutaciones, ejemplos) | [demo/gateway/README.md](demo/gateway/README.md) |
| Interfaz web (React) | [demo/frontend/](demo/frontend/) |
| Sistema base y cómo levantarlo | [demo/README.md](demo/README.md) |
| Guía de ejecución y pruebas | [demo/docs/guia-ejecucion-y-pruebas.md](demo/docs/guia-ejecucion-y-pruebas.md) |
| Despliegue en Kubernetes de Ozy, gateway e interfaz (probes, HPA, CI/CD, evidencia) | [demo/ozy/k8s/README.md](demo/ozy/k8s/README.md) |
| Pipeline de CI/CD | [.github/workflows/ozy-k8s.yml](.github/workflows/ozy-k8s.yml) |
| Decisiones de arquitectura (ADR) | [demo/docs/decisiones/](demo/docs/decisiones/) |
| Diagramas de secuencia de Ozy | `ozy-secuencias(1)-*.drawio.png` en esta carpeta |

### Levantar todo

Primero [configura la contraseña local de RabbitMQ](demo/README.md#ejecución-local).

```bash
cd demo
docker compose up --build
```

Luego abre:

| Qué | URL |
|---|---|
| Interfaz web | <http://localhost:3000> |
| GraphiQL del gateway | <http://localhost:8080/graphql> |
| Swagger de Ozy | <http://localhost:8004/docs> |

### Uso de IA

El código de Ozy se generó con apoyo de IA (Claude Code, de Anthropic). El diseño,
la arquitectura y las decisiones son del grupo, que revisó y aprobó lo generado.
Detalle en [demo/ozy/README.md#uso-de-ia](demo/ozy/README.md#uso-de-ia).

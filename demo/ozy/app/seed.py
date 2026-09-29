"""Glosario inicial con los términos de la presentación del equipo."""
from app.domain import Ambito, Estado, GlossaryEntry
from app.repositories import GlossaryRepository

SEED: list[tuple[str, Ambito, str]] = [
    ("API", Ambito.SOFTWARE,
     "Puerta de entrada que permite que dos sistemas se hablen y se pidan datos "
     "entre sí de forma ordenada."),
    ("Deploy", Ambito.SOFTWARE,
     "Poner una versión nueva del sistema en funcionamiento para que la usen las "
     "personas."),
    ("Branch", Ambito.SOFTWARE,
     "Copia paralela del código donde alguien trabaja un cambio sin afectar la "
     "versión principal."),
    ("PR", Ambito.SOFTWARE,
     "Pull Request: solicitud para que el equipo revise un cambio de código antes "
     "de sumarlo a la versión principal."),
    ("PR", Ambito.MARKETING,
     "Public Relations (relaciones públicas): gestión de la imagen de la empresa "
     "frente a medios y público."),
    ("PR", Ambito.FINANZAS,
     "Purchase Request (solicitud de compra): pedido interno formal para comprar "
     "un bien o servicio."),
    ("Pipeline", Ambito.SOFTWARE,
     "Cadena automática de pasos (probar, construir, publicar) que recorre un "
     "cambio de código hasta llegar a producción."),
    ("Modelo", Ambito.DATOS,
     "Fórmula entrenada con datos históricos que sirve para estimar o predecir un "
     "resultado."),
    ("KPI", Ambito.DATOS,
     "Indicador clave: número que muestra si se está cumpliendo un objetivo "
     "importante."),
    ("Backlog", Ambito.PRODUCTO,
     "Lista ordenada de trabajo pendiente: ideas, mejoras y arreglos por hacer."),
    ("Roadmap", Ambito.PRODUCTO,
     "Plan que muestra qué se piensa construir y aproximadamente cuándo."),
    ("Devengado", Ambito.FINANZAS,
     "Ingreso o gasto que se registra cuando ocurre, aunque el dinero todavía no "
     "se haya pagado o cobrado."),
    ("CAC", Ambito.MARKETING,
     "Costo de Adquisición de Cliente: cuánto se gasta en promedio para conseguir "
     "un cliente nuevo."),
    ("Lead", Ambito.MARKETING,
     "Persona o empresa que mostró interés y podría convertirse en cliente."),
    ("Funnel", Ambito.MARKETING,
     "Embudo: etapas por las que pasa alguien desde que conoce el producto hasta "
     "que compra."),
    ("SLA", Ambito.OPERACIONES,
     "Acuerdo de nivel de servicio: compromiso de cuán rápido y bien se responde "
     "o se mantiene funcionando algo."),
    ("Incidencia", Ambito.OPERACIONES,
     "Problema que interrumpe o degrada un servicio y que hay que resolver."),
]


def seed_glossary(glossary: GlossaryRepository) -> None:
    """Idempotente: se puede ejecutar en cada arranque."""
    for term, ambito, definition in SEED:
        glossary.seed(GlossaryEntry(term=term, ambito=ambito, definition=definition,
                                    estado=Estado.VALIDADO))

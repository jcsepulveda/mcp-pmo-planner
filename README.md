# Motor PMO Planner

Motor independiente para interactuar con planes de Microsoft Planner (Standard) y Microsoft Dataverse / Project for the Web (Premium).

## Estructura del Proyecto

El proyecto está organizado en tres componentes:
* **Core (`core/`)**: Lógica de negocio, autenticación OAuth2 y aislamiento de datos.
* **CLI (`pmo-planner.py`)**: Interfaz de línea de comandos para uso directo y automatizaciones.
* **Servidor MCP (`server.py`)**: Servidor Model Context Protocol para integración con asistentes de IA.

---

## Seguridad y Aislamiento por Grupo

El motor requiere configurar la siguiente variable en el archivo `.env` en la raíz del proyecto:

```env
ALLOWED_GROUP_ID=00000000-0000-0000-0000-000000000000
```

Todas las consultas (CLI y MCP) se validan contra este identificador. Los accesos a grupos distintos son bloqueados localmente.

---

## Requisitos e Instalación

1. Instalar las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

2. Crear y configurar el archivo de variables de entorno:
   ```bash
   cp .env.template .env
   ```
   Completar las variables correspondientes a Azure AD / Entra ID (Tenant ID, Client ID y Client Secret).

---

## Uso de la CLI

### Consultar Planes
* **Listar planes en formato tabla:**
  ```bash
  python pmo-planner.py --planes
  ```
* **Exportar planes a un archivo JSON en la raíz:**
  ```bash
  python pmo-planner.py --planes --out
  ```
* **Exportar planes a una ruta específica:**
  ```bash
  python pmo-planner.py --planes --out /ruta/al/archivo.json
  ```
* **Ver desglose de tareas (WBS) de un plan específico:**
  ```bash
  python pmo-planner.py --detalle <PLAN_ID>
  ```
* **Exportar todos los planes con sus tareas en formato JSON:**
  ```bash
  python pmo-planner.py --planes --detalle --formato json
  ```

### Otras Consultas
* **Listar Jefes de Proyecto (PM):**
  ```bash
  python pmo-planner.py --pm
  ```
* **Listar tareas vencidas y pendientes:**
  ```bash
  python pmo-planner.py --atrasadas
  ```

---

## Integración MCP

### Claude Desktop
Añadir la configuración en `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pmo-planner": {
      "command": "python3",
      "args": [
        "/absolute/path/to/pmo-planner/server.py"
      ],
      "env": {
        "PYTHONPATH": "/absolute/path/to/pmo-planner"
      }
    }
  }
}
```

### OpenCode
Añadir al bloque `"mcp"` de `~/.config/opencode/opencode.json`:

```json
    "pmo-planner": {
      "type": "local",
      "command": [
        "python3",
        "/absolute/path/to/pmo-planner/server.py"
      ],
      "cwd": "/absolute/path/to/pmo-planner",
      "enabled": true
    }
```

### Herramientas Disponibles
* `list_authorized_plans`: Lista los planes autorizados del grupo, enriquecidos ahora con `estado_base` (`No Iniciado`, `En Curso`, `Finalizado`) y `estado_nativo` (obtenido directamente a través de `statecode`/`statuscode` desde Dataverse para proyectos Premium, o "Active" para Standard).
* `get_plan_detailed_wbs`: Obtiene tareas, dependencias, avances y personas asignadas de un plan.
* `get_plan_health_metrics`: Retorna los indicadores clave de salud de un plan (Avance Real Ponderado, Avance Esperado, Delta y Semáforo).
* `get_overdue_tasks`: Escanea tareas vencidas.
* `get_workload_summary`: Calcula la carga de trabajo de tareas activas por persona asignada.
* `get_portfolio_macro_roadmap`: Analiza el portafolio unificado cruzando iniciativas con el catálogo y configuración corporativa para generar el roadmap macro, densidad de cierres y colisiones.

---

## Changelog

### 2026-07-22
- **fix**: Usa `msdyn_taskearlieststart` como fecha de inicio real de proyectos Premium, con fallback a `msdyn_scheduledstart`. Corrige la visualización en 24 de 35 proyectos que mostraban fecha de inicio incorrecta (2025-10-23).
- **fix**: Resolución de nombres de proyecto con `or` en vez de default parameter para manejar strings vacíos en el catálogo.
- Se agregan las herramientas `get_plan_health_metrics` y `get_portfolio_macro_roadmap` a la documentación de herramientas MCP disponibles.


---

## Changelog

### 2026-07-22
- **fix**: Usa `msdyn_taskearlieststart` como fecha de inicio real de proyectos Premium, con fallback a `msdyn_scheduledstart`. Corrige la visualización en 24 de 35 proyectos que mostraban fecha de inicio incorrecta (2025-10-23 — fecha default del tenant).
- **fix**: Resolución de nombres de proyecto con `or` en vez de default parameter para manejar strings vacíos en el catálogo.
- **docs**: Se agregan las herramientas `get_plan_health_metrics` y `get_portfolio_macro_roadmap` a la documentación de herramientas MCP disponibles.

### Herramientas MCP (actualización)
* `list_authorized_plans`: Lista los planes autorizados del grupo.
* `get_plan_detailed_wbs`: Obtiene tareas, dependencias, avances y personas asignadas de un plan.
* `get_plan_health_metrics`: Retorna indicadores clave de salud (Avance Real Ponderado, Avance Esperado, Delta y Semáforo).
* `get_overdue_tasks`: Escanea tareas vencidas.
* `get_workload_summary`: Calcula la carga de trabajo por persona asignada.
* `get_portfolio_macro_roadmap`: Genera el roadmap macro del portafolio con alertas de colisión y congestión.

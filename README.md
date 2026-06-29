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
* `list_authorized_plans`: Lista los planes autorizados del grupo.
* `get_plan_detailed_wbs`: Obtiene tareas, dependencias, avances y personas asignadas de un plan.
* `get_overdue_tasks`: Escanea tareas vencidas.
* `get_workload_summary`: Calcula la carga de trabajo de tareas activas por persona asignada.

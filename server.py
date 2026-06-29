import sys
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from mcp.server.fastmcp import FastMCP

from core import PlannerService, SecurityException, get_authorized_group_id

# Configuración de logs redirigidos a stderr para no interferir con la comunicación stdio del MCP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("pmo-planner-mcp")

# Inicializamos el servidor FastMCP
mcp = FastMCP("PMO-Planner-Security-Gateway")

@mcp.tool()
def list_authorized_plans(group_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Lista todos los planes y proyectos (Standard de Graph y Premium de Dataverse) autorizados
    para el grupo configurado.
    
    Args:
        group_id: (Opcional) ID del grupo de M365/Teams a consultar. Si se omite, se usa el permitido por .env.
    """
    try:
        logger.info(f"MCP list_authorized_plans invocado")
        plans = PlannerService.list_plans(group_id)
        return {
            "status": "success",
            "group_id": "PROTECTED_TENANT_GROUP",
            "total_plans": len(plans),
            "plans": plans
        }
    except SecurityException as se:
        logger.warning(f"Intento de violación de seguridad: {se}")
        return {
            "status": "security_error",
            "message": str(se)
        }
    except Exception as e:
        logger.error(f"Error en list_authorized_plans: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@mcp.tool()
def get_plan_detailed_wbs(plan_id: str) -> Dict[str, Any]:
    """
    Retorna la estructura detallada de tareas (WBS), avances, fechas y dependencias
    de un plan específico.
    
    Args:
        plan_id: UUID o identificador único del plan/proyecto.
    """
    try:
        logger.info(f"MCP get_plan_detailed_wbs invocado para plan: {plan_id}")
        details = PlannerService.get_plan_details(plan_id)
        return {
            "status": "success",
            "plan_id": plan_id,
            "data": details
        }
    except SecurityException as se:
        logger.warning(f"Intento de violación de seguridad: {se}")
        return {
            "status": "security_error",
            "message": str(se)
        }
    except Exception as e:
        logger.error(f"Error en get_plan_detailed_wbs: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@mcp.tool()
def get_overdue_tasks(group_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Escanea todos los planes del grupo y extrae únicamente las tareas que ya vencieron
    y no están completadas (avance < 100%).
    
    Args:
        group_id: (Opcional) ID del grupo a consultar.
    """
    try:
        logger.info("MCP get_overdue_tasks invocado.")
        plans = PlannerService.list_plans(group_id)
        overdue = []
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for p in plans:
            try:
                detail = PlannerService.get_plan_details(p["id"], p["tipo"])
                for t in detail.get("tasks", []):
                    finish = t.get("finish")
                    progress = t.get("progress_percent", 0)
                    if finish and finish != "-" and finish < today_str and progress < 100.0:
                        overdue.append({
                            "plan_name": p["name"],
                            "pm": p.get("pm_responsable", "Sin Asignar"),
                            "task_name": t["name"],
                            "due_date": finish,
                            "progress": f"{progress:.1f}%",
                            "assignees": t.get("assignees", [])
                        })
            except Exception as e:
                logger.warning(f"No se pudo analizar tareas de {p['name']}: {e}")
                
        return {
            "status": "success",
            "total_overdue": len(overdue),
            "overdue_tasks": overdue
        }
    except SecurityException as se:
        return {
            "status": "security_error",
            "message": str(se)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@mcp.tool()
def get_workload_summary(group_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Calcula y consolida la carga de trabajo (número de tareas asignadas) por cada
    miembro del equipo a lo largo de todos los planes del grupo.
    
    Args:
        group_id: (Opcional) ID del grupo a consultar.
    """
    try:
        logger.info("MCP get_workload_summary invocado.")
        plans = PlannerService.list_plans(group_id)
        workload = {}
        
        for p in plans:
            try:
                detail = PlannerService.get_plan_details(p["id"], p["tipo"])
                for t in detail.get("tasks", []):
                    assignees = t.get("assignees", [])
                    progress = t.get("progress_percent", 0)
                    is_completed = progress >= 100.0
                    
                    for person in assignees:
                        if person not in workload:
                            workload[person] = {
                                "active_tasks": 0,
                                "completed_tasks": 0,
                                "plans_involved": set()
                            }
                        workload[person]["plans_involved"].add(p["name"])
                        if is_completed:
                            workload[person]["completed_tasks"] += 1
                        else:
                            workload[person]["active_tasks"] += 1
            except Exception as e:
                logger.warning(f"Error al analizar carga en plan {p['name']}: {e}")
                
        # Convertir sets a listas para serialización JSON
        formatted_workload = {}
        for person, data in workload.items():
            formatted_workload[person] = {
                "active_tasks": data["active_tasks"],
                "completed_tasks": data["completed_tasks"],
                "plans_involved": list(data["plans_involved"])
            }
            
        return {
            "status": "success",
            "workload": formatted_workload
        }
    except SecurityException as se:
        return {
            "status": "security_error",
            "message": str(se)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@mcp.resource("planner://authorized-group/configuration")
def get_authorized_config() -> str:
    """Retorna información descriptiva del grupo de trabajo y su ID blindado en el servidor."""
    return "Servidor PMO-Planner. Grupo Autorizado ID: PROTECTED_TENANT_GROUP. Estado: Protegido."

if __name__ == "__main__":
    logger.info("Iniciando Servidor MCP PMO-Planner Gateway...")
    mcp.run()

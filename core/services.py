import os
import urllib.parse
import sys
from core.clients import GraphClient, DataverseClient
from core.security import validate_and_enforce_group_access, SecurityException

class PlannerService:
    _user_cache = {} # Map ID -> Name (across Graph and Dataverse)

    @classmethod
    def get_graph_user_name(cls, user_id: str) -> str:
        if not user_id:
            return "Sin Asignar"
        if user_id in cls._user_cache:
            return cls._user_cache[user_id]
        try:
            res = GraphClient.get(f"users/{user_id}", {"$select": "displayName"})
            name = res.get("displayName", "Usuario Desconocido")
            cls._user_cache[user_id] = name
            return name
        except Exception:
            return "Usuario Desconocido"

    @classmethod
    def get_dataverse_user_name(cls, user_id: str) -> str:
        if not user_id:
            return "Sin Asignar"
        if user_id in cls._user_cache:
            return cls._user_cache[user_id]
        try:
            res = DataverseClient.get(f"systemusers({user_id})", {"$select": "fullname"})
            name = res.get("fullname", "Sin Asignar")
            cls._user_cache[user_id] = name
            return name
        except Exception:
            return "Sin Asignar"

    @classmethod
    def get_group_owners_as_pms(cls, group_id: str) -> list:
        """
        Retorna los nombres de los dueños del grupo de Teams/M365 para usar como PMs por defecto en planes Standard.
        """
        try:
            res = GraphClient.get(f"groups/{group_id}/owners", {"$select": "displayName,id"})
            owners = [o.get("displayName") for o in res.get("value", []) if o.get("displayName")]
            return owners or ["Sin Asignar"]
        except Exception:
            return ["Sin Asignar"]

    @classmethod
    def list_plans(cls, group_id: str = None) -> list:
        """
        Lista todos los planes (Standard y Premium) autorizados para el grupo dado.
        """
        # Blindaje de seguridad
        safe_group_id = validate_and_enforce_group_access(group_id)
        plans = []

        # --- 1. Buscar Planes Standard en Microsoft Graph ---
        try:
            # Obtener dueños del grupo para usarlos como PM por defecto
            group_owners = cls.get_group_owners_as_pms(safe_group_id)
            default_pm = group_owners[0] if group_owners else "Sin Asignar"

            graph_plans_data = GraphClient.get(f"groups/{safe_group_id}/planner/plans")
            graph_plans = graph_plans_data.get("value", [])
            for p in graph_plans:
                plans.append({
                    "id": p.get("id"),
                    "name": p.get("title"),
                    "tipo": "Standard",
                    "progress": 0.0, # Se calculará acumulando tareas si se solicita detalle
                    "start_date": None,
                    "finish_date": None,
                    "pm_responsable": default_pm,
                    "group_id": "PROTECTED_TENANT_GROUP"
                })
        except Exception as e:
            # Toleramos que falle si no hay permisos de Graph, pero lo registramos
            print(f"[Aviso] No se pudieron obtener planes de Graph: {e}", file=sys.stderr)

        # --- 2. Buscar Planes Premium en Microsoft Dataverse ---
        try:
            # Primero resolvemos el team_id en Dataverse usando el group_id de AD
            team_res = DataverseClient.get("teams", {"$filter": f"azureactivedirectoryobjectid eq {safe_group_id}", "$select": "teamid,name"})
            team_values = team_res.get("value", []) if team_res else []
            if team_values:
                team_id = team_values[0]["teamid"]
                
                # Buscamos proyectos en Dataverse asignados a ese equipo
                projects = DataverseClient.get(
                    "msdyn_projects", 
                    {"$filter": f"_ownerid_value eq {team_id}", "$select": "msdyn_projectid,msdyn_subject,msdyn_progress,msdyn_scheduledstart,msdyn_finish,_createdby_value,_msdyn_projectmanager_value"}, 
                    get_all=True
                )
                for p in projects:
                    creator_id = p.get("_createdby_value")
                    manager_id = p.get("_msdyn_projectmanager_value")
                    pm_id = manager_id if manager_id else creator_id
                    pm_name = cls.get_dataverse_user_name(pm_id)

                    start = p.get("msdyn_scheduledstart")
                    finish = p.get("msdyn_finish")
                    if start: start = start.split('T')[0]
                    if finish: finish = finish.split('T')[0]

                    plans.append({
                        "id": p.get("msdyn_projectid"),
                        "name": p.get("msdyn_subject"),
                        "tipo": "Premium",
                        "progress": (p.get("msdyn_progress") or 0.0) * 100,
                        "start_date": start,
                        "finish_date": finish,
                        "pm_responsable": pm_name,
                        "group_id": "PROTECTED_TENANT_GROUP"
                    })
        except Exception as e:
            print(f"[Aviso] No se pudieron obtener planes de Dataverse: {e}", file=sys.stderr)

        return plans

    @classmethod
    def get_plan_details(cls, plan_id: str, tipo_plan: str = None) -> dict:
        """
        Retorna las tareas, WBS y dependencias de un plan específico.
        Si tipo_plan es None, intenta determinar si es Premium o Standard.
        """
        # BLINDAJE DE SEGURIDAD EN EL NÚCLEO: Validar pertenencia del plan
        authorized_plans = cls.list_plans()
        authorized_ids = {p["id"].lower() for p in authorized_plans}
        if plan_id.lower() not in authorized_ids:
            raise SecurityException(
                f"ACCESO DENEGADO: El plan '{plan_id}' no pertenece al grupo de trabajo autorizado."
            )

        # Resolver tipo de plan si no se especifica
        if not tipo_plan:
            # Verificamos si existe en Dataverse
            try:
                test_res = DataverseClient.get(f"msdyn_projects({plan_id})", {"$select": "msdyn_projectid,msdyn_subject"})
                if test_res and "msdyn_projectid" in test_res:
                    tipo_plan = "Premium"
            except Exception:
                tipo_plan = "Standard"

        if tipo_plan == "Premium":
            return cls._get_premium_plan_details(plan_id)
        else:
            return cls._get_standard_plan_details(plan_id)

    @classmethod
    def _get_standard_plan_details(cls, plan_id: str) -> dict:
        # Obtener metadatos del plan
        plan_meta = GraphClient.get(f"planner/plans/{plan_id}")
        
        # Obtener tareas
        tasks_data = GraphClient.get(f"planner/plans/{plan_id}/tasks")
        tasks = tasks_data.get("value", [])

        formatted_tasks = []
        total_progress = 0.0
        
        for t in tasks:
            title = t.get("title", "Sin título")
            prog = t.get("percentComplete", 0)
            total_progress += prog
            
            start = t.get("startDateTime")
            finish = t.get("dueDateTime")
            if start: start = start.split('T')[0]
            if finish: finish = finish.split('T')[0]

            formatted_tasks.append({
                "seq": len(formatted_tasks) + 1,
                "outline_level": 1,
                "name": title,
                "start": start or "-",
                "finish": finish or "-",
                "duration_days": None,
                "progress_percent": float(prog),
                "predecessors": [],
                "id": t.get("id"),
                "assignees": [cls.get_graph_user_name(u) for u in t.get("assignments", {}).keys()]
            })

        avg_progress = (total_progress / len(tasks)) if tasks else 0.0

        return {
            "project": {
                "id": plan_id,
                "name": plan_meta.get("title", "Plan Standard"),
                "tipo": "Standard",
                "progress": avg_progress,
                "start_date": None,
                "finish_date": None,
                "pm_responsable": "Ver en planes" # Se puede complementar si se desea
            },
            "tasks": formatted_tasks
        }

    @classmethod
    def _get_premium_plan_details(cls, plan_id: str) -> dict:
        # 1. Metadatos del proyecto
        proj_data = DataverseClient.get(f"msdyn_projects({plan_id})", {"$select": "msdyn_projectid,msdyn_subject,msdyn_progress,msdyn_scheduledstart,msdyn_finish,msdyn_duration,_msdyn_projectmanager_value,_createdby_value"})
        
        # 2. Obtener tareas
        filter_str = f"_msdyn_project_value eq {plan_id}"
        tasks_data = DataverseClient.get(
            "msdyn_projecttasks", 
            {"$filter": filter_str, "$orderby": "msdyn_displaysequence"},
            get_all=True
        )
        tasks = tasks_data if tasks_data else []

        # 3. Obtener dependencias
        deps_data = DataverseClient.get(
            "msdyn_projecttaskdependencies",
            {"$filter": filter_str},
            get_all=True
        )
        dependencies = deps_data if deps_data else []

        # Mapear nombres de tareas para dependencias
        task_names = {t['msdyn_projecttaskid']: t['msdyn_subject'] for t in tasks if 'msdyn_projecttaskid' in t}
        task_dependencies = {}
        for dep in dependencies:
            pred_id = dep.get('_msdyn_predecessortask_value')
            succ_id = dep.get('_msdyn_successortask_value')
            pred_name = task_names.get(pred_id, "Tarea Desconocida")
            if succ_id not in task_dependencies:
                task_dependencies[succ_id] = []
            task_dependencies[succ_id].append(pred_name)

        # Formatear tareas
        formatted_tasks = []
        for t in tasks:
            subj = t.get('msdyn_subject', 'Sin título')
            level = t.get('msdyn_outlinelevel', 1)
            start = t.get('msdyn_start')
            finish = t.get('msdyn_finish')
            if start: start = start.split('T')[0]
            if finish: finish = finish.split('T')[0]
            
            prog = t.get('msdyn_progress', 0.0)
            task_id = t.get('msdyn_projecttaskid')
            preds = task_dependencies.get(task_id, [])

            formatted_tasks.append({
                "seq": t.get('msdyn_displaysequence', 0.0),
                "outline_level": level,
                "name": subj,
                "start": start or "-",
                "finish": finish or "-",
                "duration_days": t.get('msdyn_duration'),
                "progress_percent": float(prog * 100),
                "predecessors": preds,
                "id": task_id,
                "assignees": []
            })

        creator_id = proj_data.get("_createdby_value")
        manager_id = proj_data.get("_msdyn_projectmanager_value")
        pm_id = manager_id if manager_id else creator_id
        pm_name = cls.get_dataverse_user_name(pm_id)

        start_date = proj_data.get('msdyn_scheduledstart')
        finish_date = proj_data.get('msdyn_finish')
        if start_date: start_date = start_date.split('T')[0]
        if finish_date: finish_date = finish_date.split('T')[0]

        return {
            "project": {
                "id": proj_data.get("msdyn_projectid"),
                "name": proj_data.get("msdyn_subject"),
                "tipo": "Premium",
                "progress": float((proj_data.get("msdyn_progress") or 0.0) * 100),
                "start_date": start_date,
                "finish_date": finish_date,
                "duration_days": proj_data.get("msdyn_duration"),
                "pm_responsable": pm_name
            },
            "tasks": formatted_tasks
        }

    @classmethod
    def resolve_project_dates(cls, proj: dict, cat_entry: dict) -> tuple:
        """
        Determina de forma segura las fechas de inicio y término de un proyecto.
        """
        import datetime
        start_str = cat_entry.get("fecha_inicio")
        finish_str = cat_entry.get("fecha_fin")
        
        start_dt = None
        finish_dt = None
        
        if start_str:
            try:
                start_dt = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
            except Exception:
                pass
        if finish_str:
            try:
                finish_dt = datetime.datetime.strptime(finish_str, "%Y-%m-%d").date()
            except Exception:
                pass
                
        # Fallback a Planner/Dataverse
        if not start_dt:
            s = proj.get("start") or proj.get("start_date")
            if s and s != '-':
                try:
                    start_dt = datetime.datetime.strptime(s[:10], "%Y-%m-%d").date()
                except Exception:
                    pass
        if not finish_dt:
            f = proj.get("finish") or proj.get("finish_date")
            if f and f != '-':
                try:
                    finish_dt = datetime.datetime.strptime(f[:10], "%Y-%m-%d").date()
                except Exception:
                    pass
                    
        # Fallback por defecto si todo lo demás falla
        if not start_dt:
            start_dt = datetime.date(2026, 1, 1)
        if not finish_dt:
            finish_dt = datetime.date(2026, 12, 31)
            
        return start_dt, finish_dt

    @classmethod
    def calculate_macro_roadmap_data(cls, projects: list, catalog: dict, config: dict, horizon: str = "Anual", group_by: str = "Tipo de Proyecto") -> dict:
        """
        Procesa los proyectos para generar el Roadmap Macro, el Heatmap de Congestión y Alertas de Colisión.
        """
        import datetime
        from collections import defaultdict
        
        # 1. Definir rango del horizonte temporal (Año de referencia: 2026)
        year = 2026
        if horizon == "Anual":
            range_start = datetime.date(year, 1, 1)
            range_end = datetime.date(year, 12, 31)
        elif horizon == "Semestre 1 (S1)":
            range_start = datetime.date(year, 1, 1)
            range_end = datetime.date(year, 6, 30)
        elif horizon == "Semestre 2 (S2)":
            range_start = datetime.date(year, 7, 1)
            range_end = datetime.date(year, 12, 31)
        elif horizon == "Trimestre 1 (Q1)":
            range_start = datetime.date(year, 1, 1)
            range_end = datetime.date(year, 3, 31)
        elif horizon == "Trimestre 2 (Q2)":
            range_start = datetime.date(year, 4, 1)
            range_end = datetime.date(year, 6, 30)
        elif horizon == "Trimestre 3 (Q3)":
            range_start = datetime.date(year, 7, 1)
            range_end = datetime.date(year, 9, 30)
        elif horizon == "Trimestre 4 (Q4)":
            range_start = datetime.date(year, 10, 1)
            range_end = datetime.date(year, 12, 31)
        else: # Todos
            range_start = None
            range_end = None

        processed_projects = []
        fechas_criticas = config.get("fechas_criticas", [])
        
        # Convertir fechas críticas de config a objetos datetime.date
        criticas_parsed = []
        for fc in fechas_criticas:
            try:
                s_dt = datetime.datetime.strptime(fc["fecha_inicio"], "%Y-%m-%d").date()
                f_dt = datetime.datetime.strptime(fc["fecha_fin"], "%Y-%m-%d").date()
                criticas_parsed.append({
                    "nombre": fc["nombre"],
                    "start": s_dt,
                    "finish": f_dt,
                    "color": fc.get("color", "#ef4444"),
                    "tipo": fc.get("tipo", "General")
                })
            except Exception:
                pass

        # 2. Procesar y filtrar proyectos
        for proj in projects:
            pid = proj.get("id")
            cat_entry = catalog.get(pid, {})
            
            p_start, p_finish = cls.resolve_project_dates(proj, cat_entry)
            
            # Filtrar por horizonte temporal (si se solapa con el rango)
            if range_start and range_end:
                if p_finish < range_start or p_start > range_end:
                    continue # Proyecto fuera del horizonte temporal

            pm = cat_entry.get("pm_responsable", "Sin Asignar") or "Sin Asignar"
            tipo = cat_entry.get("tipo_proyecto", "De Unidad")
            gobierno = cat_entry.get("gobierno", "Seguimiento de Jefatura")
            
            # Resolver Swimlane de agrupación
            if group_by == "Jefe de Proyecto":
                swimlane = pm
            elif group_by == "Gobierno":
                swimlane = gobierno
            else:
                swimlane = tipo

            # Calcular colisiones del término del proyecto con las fechas críticas
            colisiones_fc = []
            for fc in criticas_parsed:
                # El proyecto termina dentro de la fecha crítica o tiene intersección con ella
                if fc["start"] <= p_finish <= fc["finish"]:
                    colisiones_fc.append(fc["nombre"])

            processed_projects.append({
                "id": pid,
                "nombre": cat_entry.get("nombre_oficial", proj.get("name")),
                "start": p_start,
                "finish": p_finish,
                "pm": pm,
                "tipo": tipo,
                "gobierno": gobierno,
                "swimlane": swimlane,
                "colisiones_fc": colisiones_fc,
                "score": cat_entry.get("score", 4)
            })

        # 3. Detectar colisiones por proximidad (cierres simultáneos de un mismo PM)
        projs_by_pm = defaultdict(list)
        for p in processed_projects:
            if p["pm"] != "Sin Asignar":
                projs_by_pm[p["pm"]].append(p)
                
        alertas = []
        for pm_name, p_list in projs_by_pm.items():
            for i in range(len(p_list)):
                for j in range(i + 1, len(p_list)):
                    p1 = p_list[i]
                    p2 = p_list[j]
                    
                    diff = abs((p1["finish"] - p2["finish"]).days)
                    if diff <= 10:
                        alertas.append({
                            "tipo": "cierres_simultaneos",
                            "pm": pm_name,
                            "proyecto1": p1["nombre"],
                            "proyecto2": p2["nombre"],
                            "dias_diferencia": diff,
                            "mensaje": f"⚠️ **Cierres Simultáneos:** El PM **{pm_name}** tiene asignados los proyectos **{p1['nombre']}** y **{p2['nombre']}** que finalizan con solo {diff} días de diferencia."
                        })

        # Registrar alertas de choque con fechas críticas
        for p in processed_projects:
            for col_fc in p["colisiones_fc"]:
                alertas.append({
                    "tipo": "choque_fecha_critica",
                    "proyecto": p["nombre"],
                    "fecha_critica": col_fc,
                    "fecha_termino": p["finish"].strftime("%Y-%m-%d"),
                    "mensaje": f"🚨 **Conflicto Corporativo:** El proyecto **{p['nombre']}** finaliza el {p['finish'].strftime('%Y-%m-%d')} durante la ventana de riesgo **'{col_fc}'**."
                })

        # 4. Calcular congestión de cierres (conteo de finalizaciones de proyectos por mes en el año 2026)
        congestion_mensual = defaultdict(int)
        for m in range(1, 13):
            congestion_mensual[f"2026-{m:02d}"] = 0
            
        for p in processed_projects:
            p_finish = p["finish"]
            if p_finish.year == 2026:
                key = f"2026-{p_finish.month:02d}"
                congestion_mensual[key] += 1

        congestions = [{"mes": k, "cantidad": v} for k, v in sorted(congestion_mensual.items())]

        return {
            "projects": processed_projects,
            "fechas_criticas": criticas_parsed,
            "alertas": alertas,
            "congestion": congestions
        }


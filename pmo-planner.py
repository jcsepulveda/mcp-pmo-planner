#!/usr/bin/env python3
import sys
import os
import argparse
import json
from datetime import datetime

# Añadir el directorio actual al path por si se ejecuta directamente
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import PlannerService, SecurityException

def print_table(headers, rows):
    """Imprime una tabla formateada en consola de forma estética."""
    if not rows:
        print("Sin datos para mostrar.")
        return

    # Calcular anchos de columna
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val)))

    # Línea divisoria
    sep = "+" + "+".join(["-" * (w + 2) for w in col_widths]) + "+"
    
    # Encabezado
    header_str = "|" + "|".join([f" {headers[i]:<{col_widths[i]}} " for i in range(len(headers))]) + "|"
    print(sep)
    print(header_str)
    print(sep)

    # Filas
    for row in rows:
        row_str = "|" + "|".join([f" {str(row[i]):<{col_widths[i]}} " for i in range(len(row))]) + "|"
        print(row_str)
    print(sep)

def main():
    parser = argparse.ArgumentParser(
        description="CLI Motor PMO Planner - Consulta de planes, WBS y Jefes de Proyecto."
    )
    parser.add_argument(
        "--planes", 
        action="store_true", 
        help="Listar todos los planes/proyectos autorizados para el grupo."
    )
    parser.add_argument(
        "--detalle", 
        nargs="?", 
        const="ALL", 
        metavar="PLAN_ID", 
        help="Muestra el desglose de tareas (WBS). Si se especifica PLAN_ID trae solo ese, si no, se usa con --planes para traer todos."
    )
    parser.add_argument(
        "--pm", 
        action="store_true", 
        help="Listar los Jefes de Proyecto (PM) responsables de los planes."
    )
    parser.add_argument(
        "--atrasadas", 
        action="store_true", 
        help="Listar las tareas vencidas y no completadas de los planes."
    )
    parser.add_argument(
        "--formato", 
        choices=["tabla", "json"], 
        default="tabla", 
        help="Formato de salida en consola (por defecto: tabla)."
    )
    parser.add_argument(
        "--out", 
        nargs="?", 
        const="./reporte_planes.json", 
        metavar="RUTA", 
        help="Ruta para exportar los resultados en formato JSON. Si no se especifica ruta pero se usa la bandera, guarda en './reporte_planes.json'."
    )
    parser.add_argument(
        "--group", 
        help="ID del grupo a consultar (opcional, validado por seguridad)."
    )

    args = parser.parse_args()

    # Si no se proveen argumentos de acción, mostrar la ayuda
    if not (args.planes or args.detalle or args.pm or args.atrasadas):
        parser.print_help()
        sys.exit(0)

    try:
        results_data = None
        
        # --- CASO 1: Listar Planes ---
        if args.planes:
            plans = PlannerService.list_plans(args.group)
            
            # Si se solicita detalle para todos los planes
            if args.detalle == "ALL":
                detailed_plans = []
                for p in plans:
                    try:
                        detail = PlannerService.get_plan_details(p["id"], p["tipo"])
                        detailed_plans.append(detail)
                    except Exception as e:
                        print(f"[Advertencia] No se pudo obtener detalle para {p['name']}: {e}", file=sys.stderr)
                results_data = {"plans": detailed_plans}
            else:
                results_data = {"plans": plans}

        # --- CASO 2: Detalle de un plan específico ---
        elif args.detalle and args.detalle != "ALL":
            plan_id = args.detalle
            detail = PlannerService.get_plan_details(plan_id)
            results_data = detail

        # --- CASO 3: Listar PMs ---
        elif args.pm:
            plans = PlannerService.list_plans(args.group)
            pms_dict = {}
            for p in plans:
                pm = p.get("pm_responsable", "Sin Asignar")
                if pm not in pms_dict:
                    pms_dict[pm] = []
                pms_dict[pm].append({
                    "plan_id": p["id"],
                    "plan_name": p["name"],
                    "tipo": p["tipo"]
                })
            results_data = {"pms": pms_dict}

        # --- CASO 4: Listar tareas atrasadas ---
        elif args.atrasadas:
            plans = PlannerService.list_plans(args.group)
            overdue_tasks = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            for p in plans:
                try:
                    detail = PlannerService.get_plan_details(p["id"], p["tipo"])
                    for t in detail.get("tasks", []):
                        finish = t.get("finish")
                        progress = t.get("progress_percent", 0)
                        if finish and finish != "-" and finish < today_str and progress < 100.0:
                            overdue_tasks.append({
                                "plan_id": p["id"],
                                "plan_name": p["name"],
                                "task_id": t["id"],
                                "task_name": t["name"],
                                "due_date": finish,
                                "progress": f"{progress:.1f}%",
                                "pm": p.get("pm_responsable", "Sin Asignar")
                            })
                except Exception as e:
                    print(f"[Advertencia] Error al buscar tareas vencidas en {p['name']}: {e}", file=sys.stderr)
            
            results_data = {"overdue_tasks": overdue_tasks}

        # --- PRESENTACIÓN DE RESULTADOS ---
        if results_data is None:
            print("No se encontraron resultados.")
            sys.exit(0)

        # 1. Exportar a archivo si se solicita
        if args.out:
            out_path = os.path.abspath(args.out)
            # Asegurar que existan directorios padres
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results_data, f, indent=2, ensure_ascii=False)
            print(f"\n[Éxito] Reporte exportado a JSON en: {out_path}\n")

        # 2. Mostrar en terminal en el formato deseado
        if args.formato == "json":
            print(json.dumps(results_data, indent=2, ensure_ascii=False))
        else:
            # Formatear la salida como tabla bonita para humanos
            if "plans" in results_data and args.detalle != "ALL":
                headers = ["TIPO", "ID PLAN/PROYECTO", "NOMBRE DEL PLAN", "PROGRESO", "PM RESPONSABLE"]
                rows = []
                for p in results_data["plans"]:
                    rows.append([
                        p["tipo"],
                        p["id"],
                        p["name"],
                        f"{p['progress']:.1f}%",
                        p["pm_responsable"]
                    ])
                print_table(headers, rows)

            elif "project" in results_data and "tasks" in results_data:
                proj = results_data["project"]
                print(f"\nPROYECTO: {proj['name']} ({proj['tipo']})")
                print(f"ID:       {proj['id']}")
                print(f"PM:       {proj.get('pm_responsable', 'Sin Asignar')}")
                print(f"Avance Real Simple: {proj['progress']:.1f}%")
                if "avance_real_ponderado" in proj:
                    print(f"Avance Real Ponderado (WBS): {proj['avance_real_ponderado']:.1f}%")
                    print(f"Avance Esperado:             {proj['avance_esperado']:.1f}%")
                    print(f"Desviación (Delta):          {proj['delta']:.1f}% ({proj['semaforo'].upper()})")
                print(f"Fechas:   Inicio: {proj.get('start_date') or '-'} | Fin: {proj.get('finish_date') or '-'}\n")
                
                headers = ["SEQ", "NIVEL", "TAREA", "INICIO", "VENCE", "AV. REAL", "PESO (DÍAS)", "AV. ESP.", "PREDECESORES"]
                rows = []
                for t in results_data["tasks"]:
                    indent = "  " * (t["outline_level"] - 1)
                    task_display = f"{indent}{t['name']}"
                    if len(task_display) > 40:
                        task_display = task_display[:37] + "..."
                        
                    peso_val = t.get("peso_dias_habiles", "-")
                    esp_val = f"{t['avance_esperado']:.0f}%" if "avance_esperado" in t else "-"

                    rows.append([
                        t["seq"],
                        t["outline_level"],
                        task_display,
                        t["start"],
                        t["finish"],
                        f"{t['progress_percent']:.0f}%",
                        peso_val,
                        esp_val,
                        ", ".join(t["predecessors"]) if t["predecessors"] else "-"
                    ])
                print_table(headers, rows)

            elif "pms" in results_data:
                headers = ["PM RESPONSABLE", "PLANES ASOCIADOS"]
                rows = []
                for pm, p_list in results_data["pms"].items():
                    plan_names = [p["plan_name"] for p in p_list]
                    rows.append([pm, ", ".join(plan_names)])
                print_table(headers, rows)

            elif "overdue_tasks" in results_data:
                headers = ["PLAN", "PM", "TAREA VENCIDA", "VENCE", "AVANCE"]
                rows = []
                for ot in results_data["overdue_tasks"]:
                    rows.append([
                        ot["plan_name"],
                        ot["pm"],
                        ot["task_name"],
                        ot["due_date"],
                        ot["progress"]
                    ])
                print_table(headers, rows)

            elif "plans" in results_data and args.detalle == "ALL":
                # Si se traen todos los planes con detalle en formato tabla, resumimos
                print("\nDetalle de todos los planes cargados. Use '--formato json' para el árbol jerárquico completo.")
                for detail in results_data["plans"]:
                    proj = detail["project"]
                    print(f"- {proj['name']} ({proj['tipo']}) - PM: {proj.get('pm_responsable')} - {len(detail['tasks'])} tareas.")

    except SecurityException as se:
        print(f"\n[ERROR DE SEGURIDAD] {se}\n", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}\n", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

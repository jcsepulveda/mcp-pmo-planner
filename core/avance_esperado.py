"""Avance real ponderado + avance esperado para planes WBS.

Módulo autocontenido (solo librería estándar de Python) que calcula, sobre la
salida de tareas que ya produce el motor PMO Planner, dos métricas que hoy no
están:

1. **Avance real ponderado (bottom-up).** En vez de promediar tareas por igual,
   pondera cada tarea por su **peso = días hábiles de duración**, y hace rollup
   por la jerarquía WBS (agrupadores = promedio ponderado de sus hijos). Una
   tarea de 20 días pesa 20x una de 1 día.

2. **Avance esperado (por cronograma).** Cuánto avance "debería" llevar el plan
   hoy según el tiempo transcurrido, en días hábiles:
       ref >= fin   -> 100%
       ref < inicio  -> 0%
       si no        -> días_hábiles_transcurridos / días_hábiles_totales * 100
   El rollup usa los mismos pesos que el avance real.

El **delta = real − esperado** es el semáforo de atraso real: detecta una tarea
en curso pero rezagada (debería ir 60% y va 30%) antes de que venza.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


# =========================================================
# Días hábiles (lunes a viernes, con feriados opcionales)
# =========================================================

def previous_business_day(reference: date, holidays: Optional[set[date]] = None) -> date:
    """Día hábil anterior a `reference` (retrocede sobre fines de semana y feriados)."""
    holidays = holidays or set()
    candidate = reference - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate -= timedelta(days=1)
    return candidate


def count_business_days(start: date, end: date, holidays: Optional[set[date]] = None) -> int:
    """Días hábiles entre start y end (inclusive). Mínimo 1."""
    if end < start:
        return 1
    holidays = holidays or set()
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return max(1, count)


def elapsed_business_days(start: date, reference: date, holidays: Optional[set[date]] = None) -> int:
    """Días hábiles transcurridos desde start hasta reference (inclusive). 0 si reference<start."""
    if reference < start:
        return 0
    holidays = holidays or set()
    count = 0
    current = start
    while current <= reference:
        if current.weekday() < 5 and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


# =========================================================
# Árbol WBS reconstruido desde outline_level + orden
# =========================================================

class WBSNode:
    """Nodo del árbol WBS. Hoja o agrupador."""

    __slots__ = (
        "name", "seq", "level", "inicio", "fin", "progreso",
        "children", "peso", "real_ponderado", "esperado_ponderado",
    )

    def __init__(self, name: str, seq: float, level: int,
                 inicio: Optional[date], fin: Optional[date], progreso: float):
        self.name = name
        self.seq = seq
        self.level = level
        self.inicio = inicio
        self.fin = fin
        self.progreso = progreso          # 0-100, reportado
        self.children: list[WBSNode] = []
        self.peso = 1                     # días hábiles (se calcula)
        self.real_ponderado: Optional[float] = None
        self.esperado_ponderado: Optional[float] = None

    @property
    def es_hoja(self) -> bool:
        return not self.children


def build_tree(tasks: list[dict]) -> list[WBSNode]:
    """Reconstruye el árbol jerárquico desde una lista plana ordenada por `seq`.

    Usa `outline_level` con un algoritmo de pila: un nodo es hijo del último
    nodo previo cuyo nivel sea estrictamente menor. Robusto ante saltos de nivel.
    """
    nodes = [
        WBSNode(
            name=str(t.get("name", "")),
            seq=_to_float(t.get("seq"), default=float(i)),
            level=int(t.get("outline_level", 1) or 1),
            inicio=_parse_date(t.get("start")),
            fin=_parse_date(t.get("finish")),
            progreso=_clamp(t.get("progress_percent", 0.0)),
        )
        for i, t in enumerate(tasks)
    ]
    nodes.sort(key=lambda n: n.seq)

    roots: list[WBSNode] = []
    stack: list[WBSNode] = []
    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


# =========================================================
# Cálculo de pesos y rollups
# =========================================================

def _total_weight(node: WBSNode) -> int:
    if node.es_hoja:
        return node.peso
    total = sum(_total_weight(c) for c in node.children)
    return total if total > 0 else 1


def _compute_real(node: WBSNode, holidays: Optional[set[date]]) -> None:
    if node.es_hoja:
        node.peso = (count_business_days(node.inicio, node.fin, holidays)
                     if node.inicio and node.fin else 1)
        node.real_ponderado = node.progreso
        return
    for child in node.children:
        _compute_real(child, holidays)
    node.real_ponderado = _weighted_avg(node.children, "real_ponderado")
    node.peso = _total_weight(node)


def _compute_expected(node: WBSNode, ref: date, holidays: Optional[set[date]]) -> None:
    if node.es_hoja:
        node.esperado_ponderado = _leaf_expected(node, ref, holidays)
        return
    for child in node.children:
        _compute_expected(child, ref, holidays)
    node.esperado_ponderado = _weighted_avg(node.children, "esperado_ponderado")


def _leaf_expected(node: WBSNode, ref: date, holidays: Optional[set[date]]) -> float:
    if not node.inicio or not node.fin:
        return 0.0
    if ref >= node.fin:
        return 100.0
    if ref < node.inicio:
        return 0.0
    total = count_business_days(node.inicio, node.fin, holidays)
    elapsed = elapsed_business_days(node.inicio, ref, holidays)
    if total == 0:
        return 0.0
    return round(min(100.0, (elapsed / total) * 100), 2)


def _weighted_avg(children: list[WBSNode], attr: str) -> float:
    total_weighted = 0.0
    total_weight = 0
    for child in children:
        w = _total_weight(child)
        val = getattr(child, attr)
        if w > 0 and val is not None:
            total_weighted += val * w
            total_weight += w
    if total_weight == 0:
        return 0.0
    return round(total_weighted / total_weight, 2)


# =========================================================
# API pública
# =========================================================

def compute_plan_metrics(
    tasks: list[dict],
    reference_date: Optional[date] = None,
    holidays: Optional[set[date]] = None,
    semaforo_amarillo: float = -5.0,
    semaforo_rojo: float = -15.0,
) -> dict:
    """Calcula avance real ponderado, avance esperado y delta de un plan.

    Args:
        tasks: lista de tareas del motor.
        reference_date: fecha de corte. Default: día hábil anterior a hoy.
        holidays: feriados a excluir del conteo de días hábiles. Opcional;
                  para Chile puedes pasar `chile_holidays_2026()`.
        semaforo_amarillo / semaforo_rojo: umbrales de delta (real-esperado)
                  para el semáforo. Default: <-5 amarillo, <-15 rojo.

    Returns:
        dict con:
          avance_real_ponderado, avance_esperado, delta, semaforo,
          y `tareas`: lista por tarea con real/esperado/delta (orden WBS).
    """
    if not tasks:
        ref = reference_date or previous_business_day(date.today(), holidays)
        return {
            "fecha_referencia": ref.isoformat(),
            "avance_real_ponderado": 0.0,
            "avance_esperado": 0.0,
            "delta": 0.0,
            "semaforo": "sin_datos",
            "tareas": [],
        }

    ref = reference_date or previous_business_day(date.today(), holidays)
    roots = build_tree(tasks)

    for root in roots:
        _compute_real(root, holidays)
        _compute_expected(root, ref, holidays)

    real = _weighted_avg(roots, "real_ponderado")
    esperado = _weighted_avg(roots, "esperado_ponderado")
    delta = round(real - esperado, 2)

    return {
        "fecha_referencia": ref.isoformat(),
        "avance_real_ponderado": real,
        "avance_esperado": esperado,
        "delta": delta,
        "semaforo": _semaforo(delta, semaforo_amarillo, semaforo_rojo),
        "tareas": _flatten_report(roots),
    }


def _semaforo(delta: float, amarillo: float, rojo: float) -> str:
    if delta <= rojo:
        return "rojo"
    if delta <= amarillo:
        return "amarillo"
    return "verde"


def _flatten_report(roots: list[WBSNode]) -> list[dict]:
    out: list[dict] = []

    def walk(node: WBSNode) -> None:
        real = node.real_ponderado or 0.0
        esp = node.esperado_ponderado or 0.0
        out.append({
            "nombre": node.name,
            "nivel": node.level,
            "es_hoja": node.es_hoja,
            "peso_dias_habiles": node.peso,
            "avance_real": round(real, 2),
            "avance_esperado": round(esp, 2),
            "delta": round(real - esp, 2),
        })
        for child in node.children:
            walk(child)

    for root in roots:
        walk(root)
    return out


# =========================================================
# Helpers
# =========================================================

def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value or value == "-":
            return None
        try:
            return date.fromisoformat(value.split("T")[0])
        except ValueError:
            return None
    return None


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(100.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def chile_holidays_2026() -> set[date]:
    """Feriados legales de Chile 2026 (lista estática, sin dependencias de red)."""
    return {
        date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 4), date(2026, 5, 1),
        date(2026, 5, 21), date(2026, 6, 21), date(2026, 6, 29), date(2026, 7, 16),
        date(2026, 8, 15), date(2026, 9, 18), date(2026, 9, 19), date(2026, 10, 12),
        date(2026, 10, 31), date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 25),
    }


if __name__ == "__main__":
    import json
    demo_tasks = [
        {"seq": 1, "outline_level": 1, "name": "Fase 1", "start": "-", "finish": "-", "progress_percent": 0},
        {"seq": 2, "outline_level": 2, "name": "Tarea corta (1 día)",
         "start": "2026-06-01", "finish": "2026-06-01", "progress_percent": 100},
        {"seq": 3, "outline_level": 2, "name": "Tarea larga (20 días hábiles)",
         "start": "2026-06-01", "finish": "2026-06-26", "progress_percent": 30},
    ]
    result = compute_plan_metrics(demo_tasks, reference_date=date(2026, 6, 15), holidays=chile_holidays_2026())
    print(json.dumps(result, indent=2, ensure_ascii=False))

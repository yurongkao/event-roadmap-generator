import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

ALLOWED_ANCHORS = {"event_date", "director_start_date"}

@dataclass
class TaskTemplate:
    task_id: str
    task: str
    project: str
    anchor: str  # "event_date" | "director_start_date"
    end_offset_days: int
    duration_days: int
    depends_on: List[str]
    default_status: str


@dataclass
class ScheduledTask:
    task_id: str
    task: str
    project: str
    status: str
    start_date: date
    end_date: date

def load_templates_from_obj(raw):
    """
    raw: Python object loaded from JSON (usually list[dict])
    """
    if not isinstance(raw, list):
        raise ValueError("task templates must be a list")

    templates = []
    for i, obj in enumerate(raw):
        if not isinstance(obj, dict):
            raise ValueError(f"Task at index {i} is not a JSON object")

        templates.append(TaskTemplate(
            task_id=str(obj["task_id"]).strip(),
            task=str(obj["task"]).strip(),
            project=str(obj["project"]).strip(),
            anchor=str(obj["anchor"]).strip(),
            end_offset_days=int(obj["end_offset_days"]),
            duration_days=int(obj["duration_days"]),
            depends_on=[str(d).strip() for d in obj.get("depends_on", [])],
            default_status=str(obj["default_status"]).strip(),
        ))

    return templates

def load_templates(path: Path) -> List[TaskTemplate]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to read/parse JSON from {path}: {e}")

    if not isinstance(raw, list):
        raise ValueError("task.json must be a JSON array of task objects.")

    templates: List[TaskTemplate] = []
    for i, obj in enumerate(raw):
        if not isinstance(obj, dict):
            raise ValueError(f"Task at index {i} is not an object/dict.")

        def req(key: str):
            if key not in obj:
                raise ValueError(f"Missing required field '{key}' in task index {i}.")
            return obj[key]

        task_id = str(req("task_id")).strip()
        task = str(req("task")).strip()
        project = str(req("project")).strip()
        anchor = str(req("anchor")).strip()
        end_offset_days = req("end_offset_days")
        duration_days = req("duration_days")
        depends_on = obj.get("depends_on", [])
        default_status = str(req("default_status")).strip()

        if anchor not in ALLOWED_ANCHORS:
            raise ValueError(
                f"Invalid anchor '{anchor}' in task_id={task_id}. "
                f"Allowed: {sorted(ALLOWED_ANCHORS)}"
            )
        if not isinstance(end_offset_days, int):
            raise ValueError(f"end_offset_days must be int in task_id={task_id}.")
        if not isinstance(duration_days, int):
            raise ValueError(f"duration_days must be int in task_id={task_id}.")
        if duration_days < 0:
            raise ValueError(f"duration_days must be >= 0 in task_id={task_id}.")
        if not isinstance(depends_on, list) or not all(isinstance(x, str) for x in depends_on):
            raise ValueError(f"depends_on must be a list of strings in task_id={task_id}.")

        templates.append(
            TaskTemplate(
                task_id=task_id,
                task=task,
                project=project,
                anchor=anchor,
                end_offset_days=end_offset_days,
                duration_days=duration_days,
                depends_on=[d.strip() for d in depends_on if d.strip()],
                default_status=default_status,
            )
        )

    return templates


def validate_templates(templates: List[TaskTemplate]) -> None:
    ids = [t.task_id for t in templates]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        raise ValueError(f"Duplicate task_id(s) found: {sorted(dupes)}")

    id_set = set(ids)
    missing_deps = []
    for t in templates:
        for d in t.depends_on:
            if d not in id_set:
                missing_deps.append((t.task_id, d))
    if missing_deps:
        msg = "; ".join([f"{tid} depends_on missing {dep}" for tid, dep in missing_deps])
        raise ValueError(f"depends_on references unknown task_id(s): {msg}")

# Topological Sort
def topo_sort(templates: List[TaskTemplate]) -> List[str]:
    """
    Returns task_ids in topological order. Raises if a cycle exists.
    """
    graph: Dict[str, List[str]] = {t.task_id: [] for t in templates}
    indeg: Dict[str, int] = {t.task_id: 0 for t in templates}

    for t in templates:
        for dep in t.depends_on:
            graph[dep].append(t.task_id)  # dep -> t
            indeg[t.task_id] += 1

    queue = [tid for tid, deg in indeg.items() if deg == 0]
    queue.sort()

    order: List[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in graph[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
                queue.sort()

    if len(order) != len(templates):
        # cycle exists; find nodes still with indegree > 0
        cyclic = sorted([tid for tid, deg in indeg.items() if deg > 0])
        raise ValueError(f"Cycle detected in depends_on graph. Involved task_id(s): {cyclic}")

    return order


def initial_schedule(
    templates_by_id: Dict[str, TaskTemplate],
    event_date: date,
    director_start_date: date,
) -> Dict[str, ScheduledTask]:
    out: Dict[str, ScheduledTask] = {}
    for tid, t in templates_by_id.items():
        anchor_date = event_date if t.anchor == "event_date" else director_start_date
        end_date = anchor_date + timedelta(days=t.end_offset_days)
        start_date = end_date - timedelta(days=t.duration_days - 1)
        out[tid] = ScheduledTask(
            task_id=tid,
            task=t.task,
            project=t.project,
            status=t.default_status,
            start_date=start_date,
            end_date=end_date,
        )
    return out


def apply_dependency_shifts(
    order: List[str],
    templates_by_id: Dict[str, TaskTemplate],
    scheduled: Dict[str, ScheduledTask],
) -> None:
    """
    Enforce: task.start_date >= max(dep.end_date) for all deps.
    If violated, shift the task window forward by the needed delta.
    """
    for tid in order:
        t = templates_by_id[tid]
        if not t.depends_on:
            continue
        latest_dep_end = max(scheduled[d].end_date for d in t.depends_on)
        if scheduled[tid].start_date < latest_dep_end:
            delta = latest_dep_end - scheduled[tid].start_date
            scheduled[tid].start_date += delta
            scheduled[tid].end_date += delta


def clamp_to_director_start(
    scheduled: Dict[str, ScheduledTask],
    director_start_date: date,
) -> None:
    """
    Optional: ensure no task starts before director_start_date.
    Shifts any early task forward so start_date == director_start_date.
    """
    for tid, st in scheduled.items():
        if st.start_date < director_start_date:
            delta = director_start_date - st.start_date
            st.start_date += delta
            st.end_date += delta

def write_csv(path: Path, tasks: List[ScheduledTask]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Task", "Project", "Status", "Start Date", "End Date"])
        for t in tasks:
            w.writerow([
                t.task,
                t.project,
                t.status,
                t.start_date.isoformat(),
                t.end_date.isoformat(),
            ])

def generate_roadmap_rows(
    raw_tasks: Any,
    event_date: date,
    director_start_date: date,
    clamp: bool = False,
    sort_by: str = "topo",  # "topo" | "start_date" | "project_start"
) -> List[Dict[str, str]]:
    """
    Core engine API:
    Input:
      - raw_tasks: Python object loaded from task.json (usually a list[dict])
      - event_date: datetime.date
      - director_start_date: datetime.date
      - clamp: if True, shift tasks that start before director_start_date forward
      - sort_by: output ordering

    Output: list of dict rows with exactly 5 columns:
      Task, Project, Status, Start Date, End Date
    """

    # 1) Parse/load raw_tasks into TaskTemplate objects (pure parsing)
    templates = load_templates_from_obj(raw_tasks)

    # 2) Validate templates (duplicate ids, bad anchors, missing deps, etc.)
    validate_templates(templates)

    # 3) Build helper maps + topological ordering (dependency-aware ordering)
    templates_by_id = {t.task_id: t for t in templates}
    order = topo_sort(templates)  # list of task_id in dependency order

    # 4) Initial schedule (compute start/end from anchor + offsets + duration)
    scheduled = initial_schedule(
        templates_by_id=templates_by_id,
        event_date=event_date,
        director_start_date=director_start_date,
    )

    # 5) Enforce dependency time constraints by shifting tasks forward if needed
    apply_dependency_shifts(
        order=order,
        templates_by_id=templates_by_id,
        scheduled=scheduled,
    )

    # 6) Optional clamp to director start (useful if you don't want tasks before start date)
    if clamp:
        clamp_to_director_start(scheduled, director_start_date)
        # clamp may re-break dependencies in edge cases, so enforce again
        apply_dependency_shifts(order, templates_by_id, scheduled)

    # 7) Convert ScheduledTask objects into rows with the 5 columns (strings)
    rows = []
    for tid in order:
        st = scheduled[tid]
        rows.append({
            "Task": st.task,
            "Project": st.project,
            "Status": st.status,
            "Start Date": st.start_date.isoformat(),
            "End Date": st.end_date.isoformat(),
        })

    # 8) Optional sorting for UI convenience (does NOT change dates, only ordering)
    if sort_by == "start_date":
        rows.sort(key=lambda r: (r["Start Date"], r["Project"], r["Task"]))
    elif sort_by == "project_start":
        rows.sort(key=lambda r: (r["Project"], r["Start Date"], r["Task"]))
    elif sort_by == "topo":
        pass
    else:
        raise ValueError("sort_by must be one of: 'topo', 'start_date', 'project_start'")

    return rows

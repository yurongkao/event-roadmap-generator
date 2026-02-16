from __future__ import annotations

import json
from typing import Dict, List, Any
from openai import OpenAI


client = OpenAI()


TASK_JSON_INSTRUCTIONS = """
You are a strict JSON generator.

Return ONLY a JSON object (no markdown, no explanation) for ONE task with EXACT keys:
- task_id: string (must use the provided next_task_id)
- task: string
- project: string (pick one from the provided project list)
- anchor: "event_date" OR "director_start_date"
- end_offset_days: integer
- duration_days: integer
- depends_on: array of task_id strings (may be empty)
- default_status: string (one of: "Not Started", "In Progress", "Done", "Milestone")

Rules:
- end_offset_days: relative to anchor date. Negative means BEFORE, positive means AFTER.
- duration_days: number of days to subtract from End Date to get Start Date.
- If the user does not mention dependencies, set depends_on to [].
- Choose a sensible project from the list if user doesn't specify.
"""


def generate_task_json(
    user_text: str,
    next_task_id: str,
    existing_projects: List[str],
    existing_task_titles: List[str],
    existing_task_ids: List[str],
) -> Dict:
    """
    Convert one-sentence description to a task JSON dict.
    """
    # Keep prompt small but grounded with your template context
    project_list = ", ".join(sorted(set(existing_projects))) if existing_projects else "Partner, Marketing, Event Execution, Landing Page, Others"

    msg = f"""
Next task_id (MUST use): {next_task_id}

Allowed project values:
{project_list}

Existing task_ids:
{", ".join(existing_task_ids[:80])}

Existing task titles (for context; avoid duplicates if possible):
{", ".join(existing_task_titles[:80])}

User request:
{user_text}
""".strip()

    # Using Chat Completions works; Responses API is also available, but keep it simple.
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": TASK_JSON_INSTRUCTIONS},
            {"role": "user", "content": msg},
        ],
        temperature=0.2,
    )

    content = resp.choices[0].message.content.strip()
    return json.loads(content)

CHECKLIST_INSTRUCTIONS = """
You are an event-ops assistant.

Return ONLY valid JSON (no markdown, no explanation) with EXACT keys:
- done_definition: string
- checklist: array of strings (5-12 items)
- risks: array of strings (3-8 items)

Guidelines:
- Be specific and actionable.
- If the task is a milestone like "Host the event", include run-of-show + contingency items.
"""

def generate_task_checklist(
    task_name: str,
    project: str,
    start_date: str,
    end_date: str,
    status: str,
    context_projects: list[str],
) -> dict[str, Any]:
    msg = f"""
Task: {task_name}
Project: {project}
Status: {status}
Start Date: {start_date}
End Date: {end_date}

Other projects in this roadmap: {", ".join(context_projects)}
""".strip()

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CHECKLIST_INSTRUCTIONS},
            {"role": "user", "content": msg},
        ],
        temperature=0.3,
        # checklist 需要一點點發散，但仍要穩定、可執行。
    )

    content = resp.choices[0].message.content.strip()
    return json.loads(content)

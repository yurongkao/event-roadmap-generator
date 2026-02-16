# generate.py
import argparse
import json
from datetime import datetime
from pathlib import Path
import csv

from src.engine import generate_roadmap_rows


def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--event_date", required=True)
    ap.add_argument("--director_start_date", required=True)
    ap.add_argument("--out", default="roadmap.csv")
    ap.add_argument("--clamp", action="store_true")
    args = ap.parse_args()

    with open(args.tasks, "r", encoding="utf-8") as f:
        raw_tasks = json.load(f)

    rows = generate_roadmap_rows(
        raw_tasks=raw_tasks,
        event_date=parse_date(args.event_date),
        director_start_date=parse_date(args.director_start_date),
        clamp=args.clamp,
        sort_by="topo",
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Task", "Project", "Status", "Start Date", "End Date"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Roadmap written to {out_path}")


if __name__ == "__main__":
    main()

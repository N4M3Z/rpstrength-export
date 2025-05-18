from __future__ import annotations
import json
import argparse
from datetime import datetime, UTC
from pathlib import Path
import requests
import browser_cookie3
import brotli
import zlib
import pandas as pd
from collections import defaultdict

CONF_DIR = Path("conf")
CONF_DIR.mkdir(exist_ok=True)

# Default muscle group ID to Obsidian link map
DEFAULT_MUSCLE_GROUP_MAP = [
    "[[Chest]]", "[[Back]]", "[[Delts]]", "[[Biceps]]",
    "[[Triceps]]", "[[Quads]]", "[[Hamstrings]]", "[[Glutes]]",
    "[[Calves]]", "[[Traps]]", "[[Forearms]]", "[[Abs]]"
]

def summarize_exercises(meso_data, exercise_lookup):
    from collections import defaultdict
    exercise_weekly = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    exercise_max_effort = defaultdict(lambda: {"weight": 0, "reps": 0})
    day_exercise_map = defaultdict(list)

    for week_index, week in enumerate(meso_data["weeks"], start=1):
        for day in week["days"]:
            label = day["label"]
            for exercise in day["exercises"]:
                ex_id = exercise["exerciseId"]
                key = (label, ex_id)
                for s in exercise["sets"]:
                    if s["weight"] is not None:
                        exercise_weekly[key][week_index]["sets"] += 1
                        if s["weight"] > exercise_max_effort[key]["weight"]:
                            exercise_max_effort[key] = {"weight": s["weight"], "reps": s["reps"]}
                if ex_id not in day_exercise_map[label]:
                    day_exercise_map[label].append(ex_id)

    return exercise_weekly, exercise_max_effort, day_exercise_map

def get_json(url: str, headers: dict) -> dict:
    headers.update({
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br"
    })
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    try:
        return response.json()
    except requests.exceptions.JSONDecodeError:
        content_type = response.headers.get("Content-Encoding", "")
        raw = response.content
        if "br" in content_type:
            decoded = brotli.decompress(raw).decode("utf-8")
        elif "gzip" in content_type:
            decoded = zlib.decompress(raw, zlib.MAX_WBITS | 16).decode("utf-8")
        elif "deflate" in content_type:
            decoded = zlib.decompress(raw).decode("utf-8")
        else:
            decoded = raw.decode("utf-8", errors="replace")
        return json.loads(decoded)

def save_json(data, path: Path):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_muscle_group_map(path: Path = None):
    if path and path.exists():
        return json.load(path.open("r", encoding="utf-8"))
    return DEFAULT_MUSCLE_GROUP_MAP

def load_exercise_lookup(headers: dict, file_path: Path = None) -> dict:
    if file_path and file_path.exists():
        with file_path.open("r", encoding="utf-8") as f:
            exercise_metadata = json.load(f)
    else:
        url = "https://training.rpstrength.com/api/training/exercises"
        exercise_metadata = get_json(url, headers)
        save_json(exercise_metadata, CONF_DIR / "exercises.json")
    return {
        exercise["id"]: {
            "name": exercise["name"],
            "muscle_group_id": exercise["muscleGroupId"],
            "equipment": exercise["exerciseType"].replace("-", " ").title()
        } for exercise in exercise_metadata
    }

def format_training_day(day: dict, week_index: int, exercise_lookup: dict, muscle_group_map: dict) -> str:
    date_str = day.get('finishedAt', '')[:10] if day.get('finishedAt') else 'TBD'
    header = f"## Week {week_index + 1} - Day {day['position'] + 1} - {day['label']} ([[{date_str}]])\n\n"
    day_sections = [header]

    for exercise_entry in day['exercises']:
        exercise_info = exercise_lookup.get(exercise_entry['exerciseId'], {})
        mg_id = exercise_info.get("muscle_group_id")
        muscle_group = muscle_group_map[mg_id - 1] if mg_id and 0 < mg_id <= len(muscle_group_map) else f"[[MuscleGroup {mg_id}]]"
        exercise_name = exercise_info.get("name", f"Exercise {exercise_entry['exerciseId']}")
        equipment_type = exercise_info.get("equipment", "Unknown")

        exercise_block = f"### {muscle_group} — [[{exercise_name}]]\n\n[[{equipment_type}]]\n\n"
        exercise_block += "| Weight | Reps |\n| ------ | ---- |\n"

        for exercise_set in exercise_entry["sets"]:
            exercise_block += f"| {exercise_set['weight']} | {exercise_set['reps']} |\n"

        day_sections.append(exercise_block + "\n")

    day_sections.append("---\n\n")
    return ''.join(day_sections)

def build_summary_chart_block(weeks, muscle_group_map):
    # Build weekly volume summary
    weekly_sets = defaultdict(lambda: defaultdict(int))
    for week_index, week in enumerate(weeks, start=1):
        for day in week.get("days", []):
            for exercise_entry in day.get("exercises", []):
                muscle_group = exercise_entry.get("muscleGroupId", None)
                if muscle_group is None:
                    continue
                for exercise_set in exercise_entry.get("sets", []):
                    weekly_sets[week_index][muscle_group] += 1
    df_summary = pd.DataFrame(weekly_sets).fillna(0).astype(int)
    # Try to rename index using muscle_group_map, fallback to str
    def mg_label(mg_id):
        return muscle_group_map[mg_id - 1] if mg_id and 0 < mg_id <= len(muscle_group_map) else f"[[MuscleGroup {mg_id}]]"
    df_summary = df_summary.rename(index=mg_label)
    table_lines = ["| Muscle | " + " | ".join(f"W{w}" for w in df_summary.columns) + " |",
                   "|" + "--------|" * (len(df_summary.columns) + 1)]
    for muscle in df_summary.index:
        row = [muscle] + [str(df_summary.loc[muscle, w]) for w in df_summary.columns]
        table_lines.append("| " + " | ".join(row) + " |")
    table_lines.append("^table")
    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
    ]
    chart_blocks = []
    for idx, muscle in enumerate(df_summary.index):
        color = colors[idx % len(colors)]
        chart_blocks.append("\n".join([
            "```chart",
            "type: bar",
            "id: table",
            f'title: "{muscle}"',
            f'select: ["{muscle}"]',
            "layout: rows",
            "width: 80%",
            "beginAtZero: true",
            f'color: "{color}"',
            "showDataLabels: true",
            "```"
        ]))
    chart_summary = "\n".join(table_lines + ["\n## Summary\n"] + chart_blocks)
    return chart_summary

def generate_mesocycle_markdown(mesocycle_data: dict, source_filename: str, exercise_lookup: dict, frontmatter_template: str, muscle_group_map: dict) -> str:
    mesocycle_title = mesocycle_data['name'].replace(' ', '_')
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    frontmatter = frontmatter_template.format(
        title=mesocycle_title,
        created=now,
        updated=now,
        source=source_filename
    )

    # Group by day label
    exercise_weekly, exercise_max_effort, day_exercise_map = summarize_exercises(mesocycle_data, exercise_lookup)

    # Build table
    week_labels = [f"W{w}" for w in range(1, len(mesocycle_data['weeks']) + 1)]
    headers = ["Exercise"] + week_labels + ["Total", "Max Weight", "Max Reps"]
    summary_lines = ["## Exercise Summary", "", "| " + " | ".join(headers) + " |", "|" + " | ".join(["---"] * len(headers)) + " |"]

    WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day_label in WEEKDAY_ORDER:
        if day_label not in day_exercise_map:
            continue
        summary_lines.append(f"| **{day_label}** " + " |" * (len(headers) - 1) + " |")
        for ex_id in day_exercise_map[day_label]:
            key = (day_label, ex_id)
            weekly_counts = [exercise_weekly[key][w]["sets"] for w in range(1, len(mesocycle_data['weeks']) + 1)]
            total_sets = sum(weekly_counts)
            max_data = exercise_max_effort[key]
            name = exercise_lookup.get(ex_id, {}).get("name", f"Exercise {ex_id}")
            max_weight = max_data["weight"] if max_data["weight"] is not None else ""
            max_reps = max_data["reps"] if max_data["reps"] is not None and max_data["reps"] >= 0 else ""
            row = [f"[[{name}]]"] + [str(s) for s in weekly_counts] + [str(total_sets), str(max_weight), str(max_reps)]
            summary_lines.append("| " + " | ".join(row) + " |")

    chart_summary = build_summary_chart_block(mesocycle_data.get("weeks", []), muscle_group_map)
    content = frontmatter + "\n\n" + "\n".join(summary_lines) + "\n\n" + chart_summary + "\n"

    for week_index, week in enumerate(mesocycle_data["weeks"]):
        for training_day in week["days"]:
            content += format_training_day(training_day, week_index, exercise_lookup, muscle_group_map)

    return content

def fetch_mesocycle_detail(api_key: str, headers: dict) -> dict | None:
    url = f"https://training.rpstrength.com/api/training/mesocycles/{api_key}"
    try:
        return get_json(url, headers)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 410:
            print(f"[410 Gone] Skipping deleted or expired mesocycle: {api_key}")
            return None
        raise

def load_headers_from_file(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    headers = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return headers

def load_mesocycles(headers, index_path: Path | None):
    if index_path and index_path.exists():
        return json.load(index_path.open("r", encoding="utf-8"))
    print("Fetching mesocycles list from API...")
    meso_list = get_json("https://training.rpstrength.com/api/training/mesocycles", headers)
    save_json(meso_list, CONF_DIR / "mesocycles.json")
    return meso_list

def resolve_unique_filename(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    i = 2
    while True:
        candidate = base_path.with_name(f"{base_path.stem} ({i}){base_path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1

def main():
    parser = argparse.ArgumentParser(
        description="Convert RP Strength mesocycles to Obsidian-compatible Markdown.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--index", type=str, required=False, help="Path to mesocycle index JSON file (optional; will fetch from API if missing)")
    parser.add_argument("--headers", type=str, required=True, help="Path to a .txt file containing headers")
    parser.add_argument("--exercises", type=str, help="Path to the exercises definition JSON file")
    parser.add_argument("--frontmatter", type=str, default="frontmatter_template.md", help="Path to frontmatter template file")
    parser.add_argument("--muscle-groups", type=str, help="Path to optional muscle group mapping JSON file")
    parser.add_argument("--save-json", action="store_true", help="If set, save the raw JSON for each mesocycle")
    args = parser.parse_args()

    # Validation of required inputs and files
    if not args.headers:
        print("Error: --headers must be provided.")
        return
    if not Path(args.headers).exists():
        print(f"Error: headers file not found at {args.headers}")
        return
    if not Path(args.frontmatter).exists():
        print(f"Error: frontmatter file not found at {args.frontmatter}")
        return
    if args.muscle_groups and not Path(args.muscle_groups).exists():
        print(f"Error: muscle_groups file not found at {args.muscle_groups}")
        return
    if args.exercises and not Path(args.exercises).exists():
        print(f"Warning: exercises file not found at {args.exercises}, will try to fetch from API")

    headers = load_headers_from_file(Path(args.headers))
    muscle_group_map = load_muscle_group_map(Path(args.muscle_groups)) if args.muscle_groups else DEFAULT_MUSCLE_GROUP_MAP
    frontmatter_template = Path(args.frontmatter).read_text(encoding="utf-8")
    exercise_lookup = load_exercise_lookup(headers, Path(args.exercises) if args.exercises else None)

    index_path = Path(args.index) if args.index else None
    meso_list = load_mesocycles(headers, index_path)

    # Create output directory if it doesn't exist
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Collect summary rows for all mesocycles
    all_exercise_summary_rows = []

    print("Available mesocycles:")
    for i, meso in enumerate(meso_list):
        print(f"{i}: {meso.get('name', 'Unnamed')}")

    selection = input("Enter mesocycle indices to process (e.g., 0,2-4): ")
    indices = set()
    for part in selection.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            if start.isdigit() and end.isdigit():
                indices.update(range(int(start), int(end) + 1))
        elif part.isdigit():
            indices.add(int(part))
    selected = [meso_list[i] for i in sorted(indices) if 0 <= i < len(meso_list)]

    for meso in selected:
        key = meso.get("key")
        if not key:
            continue

        meso_data = fetch_mesocycle_detail(key, headers)
        if not meso_data:
            continue

        # Sanitize file base name
        base_name = meso_data['name'].replace('/', '_').strip()
        output_json = resolve_unique_filename(output_dir / f"{base_name}.json")
        output_file = resolve_unique_filename(output_dir / f"{base_name}.md")

        # Save raw JSON before writing Markdown file if requested
        if args.save_json:
            save_json(meso_data, output_json)

        # --- Begin summary collection for all_exercise_summary_rows ---
        exercise_weekly, exercise_max_effort, day_exercise_map = summarize_exercises(meso_data, exercise_lookup)

        for day_label in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            if day_label not in day_exercise_map:
                continue
            for ex_id in day_exercise_map[day_label]:
                key2 = (day_label, ex_id)
                weekly_counts = [exercise_weekly[key2][w]["sets"] for w in range(1, len(meso_data["weeks"]) + 1)]
                total_sets = sum(weekly_counts)
                max_data = exercise_max_effort[key2]
                name = exercise_lookup.get(ex_id, {}).get("name", f"Exercise {ex_id}")
                all_exercise_summary_rows.append({
                    "Mesocycle": output_file.stem,
                    "Day": day_label,
                    "Exercise": name,
                    "Total Sets": total_sets,
                    "Max Weight": max_data["weight"],
                    "Max Reps": max_data["reps"] if max_data["reps"] is not None and max_data["reps"] >= 0 else "",
                    **{f"Sets W{w}": weekly_counts[w - 1] for w in range(1, len(meso_data["weeks"]) + 1)}
                })
        # --- End summary collection for all_exercise_summary_rows ---

        markdown = generate_mesocycle_markdown(meso_data, f"{key}.json", exercise_lookup, frontmatter_template, muscle_group_map)

        with output_file.open("w", encoding="utf-8") as out:
            out.write(markdown)

        print(f"Saved {output_file}")

    # After all mesocycles processed, save the all_exercise_summary_rows as CSV
    if all_exercise_summary_rows:
        import pandas as pd
        df = pd.DataFrame(all_exercise_summary_rows)
        df.to_csv(output_dir / "exercise_summary_all.csv", index=False)

if __name__ == "__main__":
    main()

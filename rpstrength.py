import json
import argparse
from datetime import datetime, UTC
from pathlib import Path
import requests
import browser_cookie3
import brotli
import zlib

# Default muscle group ID to Obsidian link map
DEFAULT_MUSCLE_GROUP_MAP = {
    1: "[[Chest]]", 2: "[[Back]]", 3: "[[Delts]]", 4: "[[Biceps]]",
    5: "[[Triceps]]", 6: "[[Quads]]", 7: "[[Hamstrings]]", 8: "[[Glutes]]",
    9: "[[Calves]]", 10: "[[Traps]]", 11: "[[Forearms]]", 12: "[[Abs]]"
}

def get_json(url: str, headers: dict) -> dict:
    headers.update({
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (RPExporter)",
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
        muscle_group = muscle_group_map.get(
            str(exercise_info.get("muscle_group_id", -1)),
            f"[[MuscleGroup {exercise_info.get('muscle_group_id', '?')}]]"
        )
        exercise_name = exercise_info.get("name", f"Exercise {exercise_entry['exerciseId']}")
        equipment_type = exercise_info.get("equipment", "Unknown")

        exercise_block = f"### {muscle_group} — [[{exercise_name}]]\n\n[[{equipment_type}]]\n\n"
        exercise_block += "| Weight | Reps |\n| ------ | ---- |\n"

        for exercise_set in exercise_entry["sets"]:
            exercise_block += f"| {exercise_set['weight']} | {exercise_set['reps']} |\n"

        day_sections.append(exercise_block + "\n")

    day_sections.append("---\n\n")
    return ''.join(day_sections)

def generate_mesocycle_markdown(mesocycle_data: dict, source_filename: str, exercise_lookup: dict, frontmatter_template: str, muscle_group_map: dict) -> str:
    mesocycle_title = mesocycle_data['name'].replace(' ', '_')
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    frontmatter = frontmatter_template.format(
        title=mesocycle_title,
        created=now,
        updated=now,
        source=source_filename
    )

    content = frontmatter + "\n"
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

def main():
    parser = argparse.ArgumentParser(description="Convert RP Strength mesocycles to Obsidian-compatible Markdown.")
    parser.add_argument("--index", type=str, required=False, help="Path to mesocycle index JSON file (optional; will fetch from API if missing)")
    parser.add_argument("--headers", type=str, required=True, help="Path to a .txt file containing headers")
    parser.add_argument("--exercises", type=str, help="Path to the exercises definition JSON file")
    parser.add_argument("--frontmatter", type=str, default="frontmatter_template.md", help="Path to frontmatter template file")
    parser.add_argument("--muscle-groups", type=str, help="Path to optional muscle group mapping JSON file")
    args = parser.parse_args()

    headers = load_headers_from_file(Path(args.headers))
    muscle_group_map = load_muscle_group_map(Path(args.muscle_groups)) if args.muscle_groups else DEFAULT_MUSCLE_GROUP_MAP
    frontmatter_template = Path(args.frontmatter).read_text(encoding="utf-8")
    exercise_lookup = load_exercise_lookup(headers, Path(args.exercises) if args.exercises else None)

    if args.index:
        index_path = Path(args.index)
        if index_path.exists():
            with index_path.open("r", encoding="utf-8") as f:
                meso_list = json.load(f)
        else:
            print(f"{args.index} not found locally. Fetching from API...")
            url = "https://training.rpstrength.com/api/training/mesocycles"
            meso_list = get_json(url, headers)
    else:
        print("No --index provided. Fetching mesocycles list from API...")
        url = "https://training.rpstrength.com/api/training/mesocycles"
        meso_list = get_json(url, headers)

    # Create output directory if it doesn't exist
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    for meso in meso_list:
        key = meso.get("key")
        if not key:
            continue

        meso_data = fetch_mesocycle_detail(key, headers)
        if not meso_data:
            continue
        markdown = generate_mesocycle_markdown(meso_data, f"{key}.json", exercise_lookup, frontmatter_template, muscle_group_map)
        output_file = output_dir / f"{meso_data['name']}.md"

        with output_file.open("w", encoding="utf-8") as out:
            out.write(markdown)

        print(f"Saved {output_file}")

if __name__ == "__main__":
    main()

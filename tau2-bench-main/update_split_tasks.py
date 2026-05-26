import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
tasks_path = SCRIPT_DIR / "data" / "tau2" / "domains" / "edu" / "tasks.json"
split_tasks_path = SCRIPT_DIR / "data" / "tau2" / "domains" / "edu" / "split_tasks.json"

def main():
    if not tasks_path.exists():
        print(f"Error: {tasks_path} does not exist.")
        return

    try:
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        
        task_ids = [task["id"] for task in tasks]
        print(f"Found {len(task_ids)} tasks.")

        split_data = {"base": task_ids}
        
        with open(split_tasks_path, "w", encoding="utf-8") as f:
            json.dump(split_data, f, indent=2, ensure_ascii=False)
        
        print(f"Updated {split_tasks_path} with {len(task_ids)} task IDs.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()

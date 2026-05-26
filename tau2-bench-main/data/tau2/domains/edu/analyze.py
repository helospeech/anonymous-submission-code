import argparse
import json
from pathlib import Path


def load_json(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return None


def _extract_tasks_object(text: str):
    if not text:
        return {}
    i = text.find('"tasks"')
    if i == -1:
        return {}
    j = text.find('{', i)
    if j == -1:
        return {}
    depth = 0
    end = None
    in_string = False
    escape = False
    for idx in range(j, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            else:
                if ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end is None:
        return {}
    obj_text = text[j:end + 1]
    try:
        return json.loads(obj_text)
    except Exception:
        return {}


def analyze(base_dir: Path):
    db = load_json(base_dir / "db.json") or {}
    tasks = load_json(base_dir / "tasks.json") or []
    split = load_json(base_dir / "split_tasks.json") or {}
    policy_path = base_dir / "policy.md"
    policy_present = policy_path.exists() and policy_path.stat().st_size > 0

    db_tasks = db.get("tasks", {})
    if not db_tasks:
        try:
            raw = (base_dir / "db.json").read_text(encoding="utf-8")
        except Exception:
            raw = ""
        db_tasks = _extract_tasks_object(raw)
    db_task_ids = list(db_tasks.keys())
    task_ids = [t.get("id") for t in tasks if isinstance(t, dict)]
    split_base = split.get("base", [])

    in_tasks_not_db = sorted(set(task_ids) - set(db_task_ids))
    in_db_not_tasks = sorted(set(db_task_ids) - set(task_ids))
    common_ids = sorted(set(task_ids) & set(db_task_ids))

    question_types_total = {}
    defects_total = {"total": 0, "open": 0, "closed": 0}
    defects_by_tag = {}
    anomalies = {"choice_missing_correct": 0, "fill_missing_answer_keywords": 0, "defects_missing_solve_function": 0, "solve_function_mismatch": 0}

    per_task = {}
    for tid in common_ids:
        tdb = db_tasks.get(tid, {})
        passages = tdb.get("passages", {})
        questions = tdb.get("questions", {})
        defects = tdb.get("defects", {})

        passage_count = len(passages)
        question_count_total = 0
        question_types = {}
        choice_missing_correct = 0
        fill_missing_answer_keywords = 0
        open_examples_count = 0

        for pid, qset in questions.items():
            if not isinstance(qset, dict):
                continue
            for qkey, q in qset.items():
                qtype = q.get("type")
                question_types[qtype] = question_types.get(qtype, 0) + 1
                question_types_total[qtype] = question_types_total.get(qtype, 0) + 1
                question_count_total += 1
                if qtype == "choice":
                    if "correct" not in q:
                        choice_missing_correct += 1
                        anomalies["choice_missing_correct"] += 1
                if qtype == "fill":
                    if "answer_keywords" not in q:
                        fill_missing_answer_keywords += 1
                        anomalies["fill_missing_answer_keywords"] += 1
                if qtype == "open":
                    if "example" in q:
                        open_examples_count += 1

        def_total = 0
        def_open = 0
        def_closed = 0
        defects_missing_solve_function = 0
        solve_function_mismatch = 0
        def_ids = set()
        by_tag = {}

        for tag, items in defects.items():
            if not isinstance(items, list):
                continue
            for d in items:
                def_total += 1
                defects_total["total"] += 1
                status = d.get("status")
                if status == "open":
                    def_open += 1
                    defects_total["open"] += 1
                else:
                    def_closed += 1
                    defects_total["closed"] += 1
                did = d.get("id")
                if did:
                    def_ids.add(did)
                sf = d.get("solve_function")
                if sf is None:
                    defects_missing_solve_function += 1
                    anomalies["defects_missing_solve_function"] += 1
                else:
                    if did and did not in sf:
                        solve_function_mismatch += 1
                        anomalies["solve_function_mismatch"] += 1
            by_tag[tag] = {
                "count": len(items) if isinstance(items, list) else 0,
                "open": sum(1 for d in items if isinstance(items, list) and isinstance(d, dict) and d.get("status") == "open"),
                "closed": sum(1 for d in items if isinstance(items, list) and isinstance(d, dict) and d.get("status") != "open"),
            }

        for tag, stats in by_tag.items():
            cur = defects_by_tag.get(tag, {"count": 0, "open": 0, "closed": 0})
            cur["count"] += stats["count"]
            cur["open"] += stats["open"]
            cur["closed"] += stats["closed"]
            defects_by_tag[tag] = cur

        per_task[tid] = {
            "passage_count": passage_count,
            "question_count_total": question_count_total,
            "question_types": question_types,
            "choice_missing_correct": choice_missing_correct,
            "fill_missing_answer_keywords": fill_missing_answer_keywords,
            "open_examples_count": open_examples_count,
            "defects_total": def_total,
            "defects_open": def_open,
            "defects_closed": def_closed,
            "defects_by_tag": by_tag,
            "defect_ids": sorted(def_ids),
            "defects_missing_solve_function": defects_missing_solve_function,
            "solve_function_mismatch": solve_function_mismatch,
        }

    split_missing = {
        "in_tasks_missing": sorted([i for i in split_base if i not in task_ids]),
        "in_db_missing": sorted([i for i in split_base if i not in db_task_ids]),
    }

    summary = {
        "dir": str(base_dir),
        "policy_present": policy_present,
        "counts": {
            "tasks_json": len(task_ids),
            "db_json": len(db_task_ids),
            "common": len(common_ids),
        },
        "question_types_total": {k: v for k, v in sorted(question_types_total.items(), key=lambda x: x[0] or "")},
        "defects_total": defects_total,
        "defects_by_tag": defects_by_tag,
        "diff": {
            "in_tasks_not_db": in_tasks_not_db,
            "in_db_not_tasks": in_db_not_tasks,
        },
        "split_missing": split_missing,
        "anomalies": anomalies,
        "per_task": per_task,
    }
    return summary


def print_summary(r: dict, details: bool):
    print("目录:", r.get("dir"))
    print("策略文件存在:", r.get("policy_present"))
    c = r.get("counts", {})
    print("任务数量(tasks.json):", c.get("tasks_json"))
    print("任务数量(db.json):", c.get("db_json"))
    print("交集任务数量:", c.get("common"))
    print("题型分布:")
    for k, v in r.get("question_types_total", {}).items():
        print(" ", k, v)
    dt = r.get("defects_total", {})
    print("缺陷总数:", dt.get("total"), "打开:", dt.get("open"), "关闭:", dt.get("closed"))
    print("标签缺陷统计:")
    for tag, s in r.get("defects_by_tag", {}).items():
        print(" ", tag, s.get("count"), "打开:", s.get("open"), "关闭:", s.get("closed"))
    d = r.get("diff", {})
    if d.get("in_tasks_not_db"):
        print("仅在tasks.json中的任务:", ", ".join(d.get("in_tasks_not_db")))
    if d.get("in_db_not_tasks"):
        print("仅在db.json中的任务:", ", ".join(d.get("in_db_not_tasks")))
    sm = r.get("split_missing", {})
    if sm.get("in_tasks_missing"):
        print("split_tasks.base在tasks.json缺失:", ", ".join(sm.get("in_tasks_missing")))
    if sm.get("in_db_missing"):
        print("split_tasks.base在db.json缺失:", ", ".join(sm.get("in_db_missing")))
    a = r.get("anomalies", {})
    print("异常统计:")
    for k, v in a.items():
        print(" ", k, v)
    if details:
        print("任务明细:")
        for tid, info in r.get("per_task", {}).items():
            print("-", tid)
            print("  passages:", info.get("passage_count"))
            print("  questions:", info.get("question_count_total"), info.get("question_types"))
            print("  defects:", info.get("defects_total"), "open:", info.get("defects_open"), "closed:", info.get("defects_closed"))
            print("  by_tag:", {k: v.get("count") for k, v in info.get("defects_by_tag", {}).items()})
            if info.get("choice_missing_correct") or info.get("fill_missing_answer_keywords"):
                print("  question_anomalies:", {
                    "choice_missing_correct": info.get("choice_missing_correct"),
                    "fill_missing_answer_keywords": info.get("fill_missing_answer_keywords"),
                })
            if info.get("defects_missing_solve_function") or info.get("solve_function_mismatch"):
                print("  defect_anomalies:", {
                    "defects_missing_solve_function": info.get("defects_missing_solve_function"),
                    "solve_function_mismatch": info.get("solve_function_mismatch"),
                })


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=str, default=str(Path(__file__).parent))
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--details", action="store_true")
    args = p.parse_args()
    base_dir = Path(args.dir)
    r = analyze(base_dir)
    print_summary(r, args.details)
    if args.out:
        out_path = Path(args.out)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

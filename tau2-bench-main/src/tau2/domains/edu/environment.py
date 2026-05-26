# src/tau2/domains/edu/environment.py
from typing import Optional
import json
from tau2.environment.environment import Environment
from tau2.data_model.tasks import Task
from .data_model import EduDB, get_db
from .tools import EduTools, EduAssistantTools
from .utils import EDU_POLICY_PATH, EDU_TASK_SET_PATH, EDU_SPLIT_TASKS_PATH

def get_environment(db: Optional[EduDB] = None, solo_mode: bool = False) -> Environment:
    db = db or get_db()
    with open(EDU_POLICY_PATH, "r", encoding="utf-8") as fp:
        policy = fp.read()
    assistant_tools = EduAssistantTools(db)
    user_tools = EduTools(db)
    env = Environment(domain_name="edu", policy=policy, tools=assistant_tools, user_tools=user_tools)
    if solo_mode:
        env.set_solo_mode(True)
    return env

def get_tasks(task_split_name: Optional[str] = "base") -> list[Task]:
    with open(EDU_TASK_SET_PATH, "r", encoding="utf-8") as fp:
        raw = json.load(fp)
    tasks = [Task.model_validate(t) for t in raw]
    if task_split_name is None:
        return tasks
    splits = get_tasks_split()
    if task_split_name not in splits:
        raise ValueError(f"Invalid task split: {task_split_name}")
    ids = set(splits[task_split_name])
    return [t for t in tasks if t.id in ids]

def get_tasks_split() -> dict[str, list[str]]:
    with open(EDU_SPLIT_TASKS_PATH, "r", encoding="utf-8") as fp:
        return json.load(fp)
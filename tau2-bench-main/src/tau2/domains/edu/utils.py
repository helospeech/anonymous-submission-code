# src/tau2/domains/edu/utils.py
from pathlib import Path
from tau2.utils import DATA_DIR

EDU_DATA_DIR = DATA_DIR / "tau2" / "domains" / "edu"
EDU_DB_PATH = EDU_DATA_DIR / "db.json"
EDU_POLICY_PATH = EDU_DATA_DIR / "policy.md"
EDU_TASK_SET_PATH = EDU_DATA_DIR / "tasks.json"
EDU_SPLIT_TASKS_PATH = EDU_DATA_DIR / "split_tasks.json"
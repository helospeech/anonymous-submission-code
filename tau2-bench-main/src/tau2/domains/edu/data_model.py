# src/tau2/domains/edu/data_model.py
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from tau2.environment.db import DB
from .utils import EDU_DB_PATH

class DefectEntry(BaseModel):
    id: str
    defect: str
    teaching_example: str
    solve_function: str
    status: str = Field(default="open")

class EduTaskData(BaseModel):
    passages: Dict[str, str] = Field(default_factory=dict)
    questions: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    defects: Dict[str, list[DefectEntry]] = Field(default_factory=dict)
    current_stage: Optional[str] = Field(default=None)

class EduDB(DB):
    tasks: Dict[str, EduTaskData] = Field(default_factory=dict)
    selected_task_id: Optional[str] = Field(default=None)

def get_db(path: Optional[str] = None) -> EduDB:
    return EduDB.load(path or str(EDU_DB_PATH))
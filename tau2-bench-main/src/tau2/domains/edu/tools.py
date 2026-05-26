# src/tau2/domains/edu/tools.py
from typing import Optional, Dict, Any
from tau2.environment.toolkit import ToolKitBase, is_tool, ToolType
from tau2.environment.tool import Tool
from .data_model import EduDB, EduTaskData

class EduTools(ToolKitBase):
    def __init__(self, db: EduDB):
        self.db = db

    def _get_selected_task_id(self) -> str:
        if self.db.selected_task_id:
            return self.db.selected_task_id
        return next(iter(self.db.tasks.keys()), "")

    def _get_task(self) -> Optional[EduTaskData]:
        tid = self._get_selected_task_id()
        return self.db.tasks.get(tid)

    def set_selected_task(self, task_id: str) -> str:
        self.db.selected_task_id = task_id
        return task_id

    @is_tool(ToolType.READ)
    def get_passage(self) -> str:
        t = self._get_task()
        return "" if t is None or not t.passages else next(iter(t.passages.values()))

    def get_questions(self, passage_id: str) -> Dict[str, Any]:
        t = self._get_task()
        return {} if t is None else t.questions.get(passage_id, {})

    def get_current_task(self) -> str:
        t = self._get_task()
        return "" if t is None else (t.current_stage or "")

    def set_current_task(self, task_id: str) -> str:
        t = self._get_task()
        if t is not None:
            t.current_stage = task_id
        return task_id

    @is_tool(ToolType.READ)
    def get_defects(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        t = self._get_task()
        if t is None:
            return {"task_id": "", "defects": []}
        stage = task_id or (t.current_stage or next(iter(t.defects.keys()), ""))
        defects = [d.model_dump() for d in t.defects.get(stage, []) if d.status != "solved"]
        return {"task_id": stage, "defects": defects}

    @is_tool(ToolType.WRITE)
    def mark_defect_solved(self, defect_id: str) -> str:
        for _, td in self.db.tasks.items():
            for d_arr in td.defects.values():
                for d in d_arr:
                    if d.id == defect_id:
                        d.status = "solved"
                        return defect_id
        raise ValueError(f"Defect {defect_id} not found")

class EduAssistantTools(EduTools):
    def get_tools(self) -> Dict[str, Tool]:
        tools = super().get_tools()
        for name in ["get_defects", "mark_defect_solved"]:
            tools.pop(name, None)
        return tools
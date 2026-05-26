import os
import json
import sys
import uuid

from llm_client import LLMClient
from sim_common import _batch_complete

IN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset_extracted.json")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tau2_data")
DB_FILE = os.path.join(OUT_DIR, "db.json")
TASKS_FILE = os.path.join(OUT_DIR, "tasks.json")

SYSTEM_PROMPT = """你是一个专业的语文教研专家。你需要根据提供的课文原文和教师教学用书，生成用于大模型的阅读理解互动数据。
你只需要输出以下 JSON 结构：
{
    "defects": {
        "D1": [
            {"id": "D1-1", "defect": "学生对课文的表层理解性缺陷1", "teaching_example": "教师引导的话术"}
        ],
        "D2": [
            {"id": "D2-1", "defect": "学生对课文的逻辑分析性缺陷1", "teaching_example": "教师引导的话术"}
        ],
        "D3": [
            {"id": "D3-1", "defect": "学生对课文的深层升华性缺陷1", "teaching_example": "教师引导的话术"}
        ]
    },
    "task_instructions": "写一段生动的内心独白，表达学生初读这篇课文时的疑惑、不懂的地方，或者对课文某些句子的误解。表现出学生的真实想法，可以带点调皮或迷茫。"
}
请注意：
1. 只输出 JSON 字符串，不要带 markdown 代码块标记，不要有任何多余的文本解释。
2. defects 必须严格按照以下三类进行定义，且总数至少包含 4 个缺陷：
   - D1 类：表层理解性缺陷 (Surface-level Comprehension Defects)。理论对应：布鲁姆分类学中的“记忆（Remember）”与“理解（Understand）”层级。
   - D2 类：逻辑分析性缺陷 (Logical Analysis Defects)。理论对应：布鲁姆分类学中的“应用（Apply）”与“分析（Analyze）”层级。
   - D3 类：深层升华性缺陷 (Deep Sublimation Defects)。理论对应：布鲁姆分类学中的“评价（Evaluate）”与“创造（Create）”层级。
3. defects 中的 id 必须以 D1-1, D2-1 这种格式按类别递增。
"""

def _build_prompt_for_lesson(lesson_data: dict) -> tuple[str, str]:
    grade_sem = lesson_data['grade_semester']
    # 判断是初中生还是高中生
    if "7年级" in grade_sem or "8年级" in grade_sem or "9年级" in grade_sem:
        student_level = "初中生"
    else:
        student_level = "高中生"
        
    system_prompt_with_persona = SYSTEM_PROMPT.replace("你是一名初中/高中生。", f"你是一名{student_level}。")
    
    prompt = f"""
【年级】：{grade_sem}
【课文标题】：《{lesson_data['lesson_title']}》
【课文内容】（截取）：
{lesson_data['textbook_content']}

【教师教参要求】（截取）：
{lesson_data['teacher_content']}

请根据以上材料，生成要求的 JSON 数据。
"""
    return system_prompt_with_persona, prompt

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # 初始化 LLM Client
    os.environ["SIM_MODEL_NAME"] = "Gemini 3-Pro-Preview"
    # Please set your API key before running: export SIM_MODEL_API_KEY="..." or export OPENROUTER_API_KEY="..."
    llm = LLMClient.from_env()
    if not llm.enabled:
        print("Error: Missing API_KEY. Please set SIM_MODEL_API_KEY or OPENROUTER_API_KEY environment variable.")
        return
        
    with open(IN_FILE, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
        
    db_data = {"tasks": {}}
    tasks_data = []
    
    # 跑全量数据
    total_to_process = len(dataset)
    
    prompts = []
    task_ids = []
    
    for i in range(total_to_process):
        lesson = dataset[i]
        title = lesson['lesson_title']
        clean_title_id = "".join(filter(str.isalnum, title))
        task_id = f"edu_{clean_title_id}_{uuid.uuid4().hex[:6]}"
        task_ids.append((i, task_id, lesson))
        
        sp, up = _build_prompt_for_lesson(lesson)
        prompts.append((sp, up))
        
    print(f"开始批量生成 {total_to_process} 篇课文的任务...")
    
    def _on_result(idx: int, raw: str | None, err: Exception | None):
        lesson_idx, task_id, lesson = task_ids[idx]
        title = lesson['lesson_title']
        
        if err:
            print(f"[{title}] 生成失败: {err}")
            return
            
        if not raw:
            print(f"[{title}] 生成失败: 返回为空")
            return
            
        try:
            response = raw.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
                
            result = json.loads(response.strip())
            
            # 从模型极简输出中提取数据并补全固定字段
            raw_defects = result.get("defects", {})
            task_instructions = result.get("task_instructions", "")
            
            # 为每个 defect 补全固定字段 solve_function 和 status
            for d_group_key, d_list in raw_defects.items():
                for defect in d_list:
                    d_id = defect.get("id", "")
                    if d_id:
                        defect["solve_function"] = f"mark_defect_solved('{d_id}')"
                        defect["status"] = "open"
            
            # 组装 DB 数据
            db_entry = {
                "passages": { "p1": lesson['textbook_content'][:1500] },
                "questions": {},
                "defects": raw_defects
            }
            db_data["tasks"][task_id] = db_entry
            
            # 提取 actions 列表
            actions = []
            for d_group in raw_defects.values():
                for defect in d_group:
                    d_id = defect["id"]
                    actions.append({
                        "action_id": f"solve_{d_id}",
                        "requestor": "assistant",
                        "name": "mark_defect_solved",
                        "arguments": {"defect_id": d_id},
                        "compare_args": ["defect_id"]
                    })
            
            # 动态判断学生身份
            grade_sem = lesson['grade_semester']
            student_level = "初中生" if any(x in grade_sem for x in ["7年级", "8年级", "9年级"]) else "高中生"
            
            task = {
                "id": task_id,
                "description": {"purpose": "语文阅读理解辅导"},
                "user_scenario": {
                    "persona": f"你是一名{student_level}。",
                    "instructions": {
                        "task_instructions": task_instructions,
                        "domain": "edu",
                        "reason_for_call": f"学习《{title}》课文。",
                        "known_info": f"原文：《{title}》\n" + lesson['textbook_content'][:300]
                    }
                },
                "evaluation_criteria": {
                    "actions": actions,
                    "reward_basis": ["DB"]
                },
                "initial_state": {
                    "initialization_actions": [{"env_type": "assistant", "func_name": "set_selected_task", "arguments": {"task_id": task_id}}],
                    "message_history": [{"role": "user", "content": f"老师，我们开始学《{title}》吧！"}]
                }
            }
            tasks_data.append(task)
            print(f"[{title}] 解析成功！")
        except Exception as e:
            print(f"[{title}] 解析 JSON 失败: {e}")

    # 调用批量生成函数
    _batch_complete(llm, prompts, "generate_qa", on_result=_on_result)
            
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n成功生成 {len(tasks_data)} 个任务。")
    print(f"数据已保存在: {OUT_DIR}")

if __name__ == "__main__":
    main()
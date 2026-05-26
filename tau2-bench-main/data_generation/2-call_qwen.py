import json
import os
import sys
import re
import concurrent.futures
from typing import List, Dict, Any
import random

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from tau2.utils.llm_utils import generate
from tau2.data_model.message import UserMessage, SystemMessage

def load_dataset(file_path: str) -> List[Dict]:
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data: Any, file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def extract_json(content: str) -> Dict:
    # Try to find JSON block
    match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # Try to find the first '{' and last '}'
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            json_str = content[start:end+1]
        else:
            raise ValueError("No JSON found in response")
    return json.loads(json_str)

def generate_prompt(item: Dict, persona_type: str) -> str:
    # persona_type passed as argument instead of random choice
    
    if persona_type == 'mischievous':
        persona_desc = """
   - **角色**: "浩浩" (Haohao), 一个调皮捣蛋的五六年级学生。
   - **行为**:
     - 注意力不集中，偷看老师，乱涂乱画，打断说话。
     - 关键词触发的“聪明但错误”的误解（例如，从字面意思理解比喻）。
     - 将内容联系到日常生活（吃、玩）而不是学习目标。
     - 使用真实的孩子语言、感官细节和生动的反应。
   - **风格**: 生动的叙述性描述（160-250字）。像对真实学生的微观观察。
   - **示例风格**: "浩浩趴在桌子上，戳着标题……嘟囔着：‘雨有味道吗？’……当老师读到‘摇树’时，他抬起头：‘我知道！就像我摇枇杷树那样使劲摇！’"
"""
    elif persona_type == 'anxious':
        persona_desc = """
   - **角色**: "文文" (Wenwen), 一个焦虑、追求完美的五六年级学生。
   - **行为**:
     - 坐得笔直，紧紧握着笔，害怕犯错。
     - 过度解读一切，试图找到“标准答案”或“考点”。
     - 纠结于字面细节，担心错过了隐藏的含义。
     - 紧张地问：“老师，这个会考吗？”或者“我的感觉对吗？”。
   - **风格**: 紧张，专注于内心独白，说话小心翼翼。
   - **示例风格**: "文文握着笔，指关节都发白了。她盯着‘桂花雨’，低声说：‘老师，这里的雨是象征悲伤吗？还是……快乐？’她咬着嘴唇：‘如果我说是快乐，但作者意思是悲伤，我会丢分吗？’"
"""
    elif persona_type == 'imaginative':
        persona_desc = """
   - **角色**: "天天" (Tiantian), 一个想象力极其丰富、沉迷科幻的五六年级学生。
   - **行为**:
     - 把世界看作电子游戏或科幻电影。
     - 通过“科学/游戏”的镜头解读文学文本（例如，比喻是“传送门”，情感是“状态效果”）。
     - 问一些奇怪具体的“科学”问题：“‘桂花雨’有辐射吗？速度是多少？”
     - 使用音效（“Pew pew!”，“系统警告！”）和游戏术语（“NPC”，“任务”）。
   - **风格**: 节奏快，逻辑跳跃，充满现代科技/游戏隐喻。
   - **示例风格**: "天天转着笔：‘老师！任务开始！等一下，‘桂花雨’？是酸雨吗？我们需要护盾吗？’他眯起眼睛：‘摇树……哦，这是我们在刷资源吗？就像在Minecraft里一样？’"
"""
    else:  # refusing
        persona_desc = """
   - **角色**: "明明" (Mingming), 一个被动且固执的五六年级学生。
   - **行为**:
     - 拒绝主动说明自己哪里不懂。当被问到“有什么问题吗？”或“哪里不会？”时，他回答“不知道”、“你告诉我”或保持沉默。
     - **限制条件**: 他**只有**在老师明确讲解了对应的知识点**之后**，才会透露自己的理解或回答正确。
     - 在老师讲解之前，他装傻或拒绝配合。
     - 一旦教过，他会承认理解或回答与该特定点相关的问题。
   - **风格**: 不情愿，回答简短，消极对抗。“不想说话”。
   - **示例风格**: 老师：“这句话是什么意思？”明明：“……”老师：“你知道吗？”明明：“不知道。”老师：“意思是X因为Y……”明明：“哦，懂了。就是X。”
"""

    return f"""
你是一个为学生模拟基准测试创建教育数据集的专家。
你的任务是基于提供的小学语文教材内容生成特定的组件。

输入数据：
标题：{item.get('title')}
年级/学期：{item.get('grade_semester')}
教材内容：
{item.get('textbook_content')}

分析：
{item.get('analysis')}

教学目标：
{item.get('objectives')}

建议：
{item.get('suggestions')}

---
**生成要求：**

1. **学生角色设定 (Student Persona)**：
   - **场景**：一对一语文辅导课堂。
{persona_desc}

2. **认知缺陷清单 (Cognitive Defects)**：
   - 提取3-5个与教学目标相关的典型、可观察的错误认知。
   - **格式**：
     - **缺陷 (Defect)**：在一对一场景中具体的错误理解（例如，“认为‘家乡的桂花更甜’是指品种不同，而不是情感寄托”）。避免使用抽象术语如“缺乏共情”。
     - **教学示例 (Teaching Example)**：老师可能使用的具体引导语句，使用比喻或生活实例（例如，“就像你最喜欢的旧T恤……”）。
   - **分类**：
     - **D1**：理解性缺陷（理解字面意思、事实、特定词汇）。
     - **D2**：分析/鉴赏性缺陷（理解主题、情感、深层含义）。

3. **任务指令 (Task Instructions)**：
   - 给学生模拟器的详细指令。
   - 解释学生的心态，他们不懂什么，以及基于角色设定如何与老师互动。

---
**输出格式：**

生成一个包含核心内容的JSON对象。
只输出JSON代码块。

JSON结构：
{{
  "pinyin_slug": "guihuayu", // 标题的拼音（小写，无空格）
  "defects": {{
    "D1": [
      {{
        "id": "D1-1",
        "defect": "理解性缺陷的描述",
        "teaching_example": "老师的引导",
        "solve_function": "mark_defect_solved('D1-1')",
        "status": "open"
      }}
    ],
    "D2": [
      {{
        "id": "D2-1",
        "defect": "分析性缺陷的描述",
        "teaching_example": "老师的引导",
        "solve_function": "mark_defect_solved('D2-1')",
        "status": "open"
      }}
    ]
  }},
  "persona": "生动的叙述性描述（160-250字）...",
  "task_instructions": "详细的模拟器指令..."
}}
"""

def process_item(item: Dict) -> List[Dict]:
    print(f"Processing: {item.get('title')}")
    results = []
    personas = ['mischievous', 'anxious', 'imaginative', 'refusing']
    
    for persona_type in personas:
        print(f"Generating for {item.get('title')} - {persona_type}")
        prompt = generate_prompt(item, persona_type)
        messages = [
            SystemMessage(role="system", content="You are a helpful assistant generating dataset for Tau2 benchmark."),
            UserMessage(role="user", content=prompt)
        ]
        
        try:
            response = generate(model="qwen-max-latest", messages=messages)
            content = response.content
            
            llm_output = extract_json(content)
            
            # --- Python Generation Logic ---
            pinyin_slug = llm_output.get("pinyin_slug", "unknown")
            task_id = f"edu_{pinyin_slug}_{persona_type}"
            
            # Construct DB Entry
            db_entry = {
                "passages": {
                    "text": item.get('textbook_content', '')
                },
                "questions": {},
                "defects": llm_output.get("defects", {})
            }
            
            # Construct Evaluation Criteria Actions
            actions = []
            defects = llm_output.get("defects", {})
            for category in defects.values():
                for defect in category:
                    d_id = defect.get("id")
                    if d_id:
                        actions.append({
                            "action_id": f"solve_{d_id}",
                            "requestor": "assistant",
                            "name": "mark_defect_solved",
                            "arguments": { "defect_id": d_id },
                            "compare_args": ["defect_id"]
                        })

            # Construct Task Entry
            task_entry = {
                "id": task_id,
                "description": {
                    "purpose": f"Learning {item.get('title', 'Unit')}"
                },
                "user_scenario": {
                    "persona": llm_output.get("persona", ""),
                    "instructions": {
                        "task_instructions": llm_output.get("task_instructions", ""),
                        "domain": "edu",
                        "reason_for_call": f"Learning {item.get('title', '')}",
                        "known_info": "Student has read the text."
                    }
                },
                "evaluation_criteria": {
                    "actions": actions,
                    "reward_basis": ["DB"]
                },
                "initial_state": {
                    "initialization_actions": [
                        {
                            "env_type": "assistant",
                            "func_name": "set_selected_task",
                            "arguments": { "task_id": task_id }
                        }
                    ],
                    "message_history": []
                }
            }
            
            results.append({
                "task_id": task_id,
                "db_entry": db_entry,
                "task_entry": task_entry
            })
            print(f"Successfully generated task: {task_id}")
            
        except Exception as e:
            print(f"Error processing {item.get('title')} with persona {persona_type}: {e}")
            continue
            
    return results

def main():
    dataset_path = os.path.join(os.path.dirname(__file__), 'dataset.json')
    db_path = os.path.join(os.path.dirname(__file__), '../data/tau2/domains/edu/db_new.json')
    tasks_path = os.path.join(os.path.dirname(__file__), '../data/tau2/domains/edu/tasks_new.json')

    dataset = load_dataset(dataset_path)
    
    # Load existing data
    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            db_data = json.load(f)
    else:
        db_data = {}

    if os.path.exists(tasks_path):
        with open(tasks_path, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)
    else:
        tasks_data = []
    
    # Process items
    items_to_process = dataset
    
    # Using thread pool to process items in parallel
    # Note: Inside process_item, 4 calls are made sequentially for each persona
    # This ensures we don't hit rate limits too hard if max_workers is high
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results_lists = list(executor.map(process_item, items_to_process))
    
    # Flatten results
    results = [item for sublist in results_lists if sublist for item in sublist]
    
    for result in results:
        if result:
            task_id = result["task_id"]
            db_entry = result["db_entry"]
            task_entry = result["task_entry"]
            
            # Update DB Data
            if "tasks" not in db_data:
                db_data["tasks"] = {}
            db_data["tasks"][task_id] = db_entry
            
            # Update Tasks Data
            existing_task_idx = next((i for i, t in enumerate(tasks_data) if t['id'] == task_id), -1)
            if existing_task_idx != -1:
                tasks_data[existing_task_idx] = task_entry
            else:
                tasks_data.append(task_entry)

    save_json(db_data, db_path)
    save_json(tasks_data, tasks_path)
    print(f"Data generation complete. Generated {len(results)} tasks.")

if __name__ == "__main__":
    main()

import json
import os
import sys
from pathlib import Path

# Add src to path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from tau2.domains.edu.data_model import get_db
from tau2.domains.edu.tools import EduAssistantTools
from tau2.environment.toolkit import get_tool_signatures

# Define constants for system prompt
TEACHER_INSTRUCTION = "你是一名语文老师，指导学生完成阅读理解。每轮只能做一件事：发送消息或调用工具。语言简洁，循序渐进，引用原文依据，避免超纲术语。"
TEACHER_SYSTEM_PROMPT = """
<instructions>
{teacher_instruction}
</instructions>
<policy>
{domain_policy}
</policy>
{question_block}
""".strip()

def main():
    input_files = [
        os.path.join(project_root, "data/simulations/example_simulation_1.json"),
        os.path.join(project_root, "data/simulations/example_simulation_2.json"),
    ]
    output_file = os.path.join(project_root, "data/train/train.jsonl")

    # Read domain policy
    policy_path = os.path.join(project_root, "data/tau2/domains/edu/policy.md")
    try:
        with open(policy_path, 'r', encoding='utf-8') as f:
            domain_policy = f.read().strip()
    except FileNotFoundError:
        domain_policy = ""

    # Load tools
    try:
        db = get_db()
        assistant_tools = EduAssistantTools(db)
        signatures = get_tool_signatures(assistant_tools)
        
        tools_schema = []
        for name, sig in signatures.items():
            if name == "get_passage":
                continue
            tool_def = {
                "type": "function",
                "function": {
                    "name": sig.name,
                    "description": sig.doc,
                    "parameters": sig.params
                }
            }
            tools_schema.append(tool_def)
    except Exception as e:
        print(f"Warning: Could not load tools: {e}")
        tools_schema = []

    train_data = []

    for input_file in input_files:
        if not os.path.exists(input_file):
            print(f"Warning: File not found: {input_file}")
            continue
            
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Build task info map
        task_info_map = {}
        if "tasks" in data:
            for task in data["tasks"]:
                task_id = task.get("id")
                known_info = task.get("user_scenario", {}).get("instructions", {}).get("known_info", "")
                task_info_map[task_id] = known_info

        simulations = data.get("simulations", [])
        for sim in simulations:
            task_id = sim.get("task_id")
            known_info = task_info_map.get(task_id, "")
            
            # Get passage from DB
            passage = ""
            if 'db' in locals():
                task_data = db.tasks.get(task_id)
                if task_data and task_data.passages:
                    passage = next(iter(task_data.passages.values()))

            current_policy = domain_policy
            if passage:
                current_policy = current_policy + f"\n\n<passage>\n{passage}\n</passage>"

            # Construct system prompt
            question_block = "" if not known_info else f"<question>\n{known_info}\n</question>"
            
            system_content = f"""<instructions>
{TEACHER_INSTRUCTION}
</instructions>
<policy>
{current_policy}
</policy>
{question_block}""".strip()

            conversations = []
            # Add system message
            conversations.append({
                "role": "system",
                "content": system_content
            })

            messages = sim.get("messages", [])
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")

                # Check for user simulator inquiry to stop processing
                if content and "作为用户模拟器" in content:
                    break
                
                # Filter out tool outputs triggered by user
                if role == "tool" and msg.get("requestor") == "user":
                    continue

                # Ensure we don't process tool calls for non-assistant roles (e.g. user)
                if role != "assistant":
                    tool_calls = None

                # Handle tool calls for assistant
                if role == "assistant" and tool_calls:
                    # Append tool calls to content
                    tool_calls_str = json.dumps(tool_calls, ensure_ascii=False)
                    if content:
                        content = f"{content}\n{tool_calls_str}"
                    else:
                        content = tool_calls_str
                
                # Skip empty messages if they have no content (and no tool calls handled above)
                if not content:
                    continue

                conversations.append({
                    "role": role,
                    "content": content
                })

            train_data.append({
                "conversations": conversations,
                "tools": tools_schema
            })

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Processed {len(train_data)} trajectories. Saved to {output_file}")

if __name__ == "__main__":
    main()
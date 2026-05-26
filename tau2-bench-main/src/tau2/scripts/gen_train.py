"""
gen_train.py - 生成训练数据的脚本

流程：
1. 带 hint（defects 信息 + 教学示例）运行 simulation，让 agent 表现更好
2. 将产生的轨迹自动转换为不含 hint 的训练数据（jsonl），
   训练后的模型在评测时不会有这些 hint
"""
import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger


# =========== 训练数据的 system prompt 模板（不含 hint）===========
TRAIN_SYSTEM_INSTRUCTION = "你是一名语文老师，指导学生完成阅读理解。每轮只能做一件事：发送消息或调用工具。语言简洁，循序渐进，引用原文依据，避免超纲术语。"

TRAIN_SYSTEM_PROMPT_TEMPLATE = """\
<instructions>
{instruction}
</instructions>
<policy>
{policy}
</policy>
{passage_block}\
{question_block}"""


def build_hint_for_task(db, task) -> str:
    """
    根据 task 对应的 DB 中的 defects 信息，构建注入给 agent 的 hint。
    提示措辞避免让 agent 暴露"我知道你有几个缺陷"这种元信息，
    而是伪装成教学参考资料，让 agent 自然地逐步覆盖这些知识点。
    """
    task_id = task.id
    task_data = db.tasks.get(task_id)
    if task_data is None:
        return ""

    hint_lines = []
    hint_lines.append("\n\n<教学参考>")
    hint_lines.append("根据本课文的教学大纲，以下是学生在该课文学习中常见的理解偏差及推荐的引导策略。")
    hint_lines.append("请在教学过程中自然地覆盖这些知识点，不要向学生透露你预先知道这些信息。")
    hint_lines.append("像一位经验丰富的老师那样，通过提问和互动自然地触及这些要点。")
    hint_lines.append("")

    for stage, defects in task_data.defects.items():
        for d in defects:
            hint_lines.append(f"• 常见误解：{d.defect}")
            hint_lines.append(f"  推荐引导方式：{d.teaching_example}")
            hint_lines.append("")

    hint_lines.append("教学要求：")
    hint_lines.append("- 不要一次性罗列所有知识点，要根据学生的回答自然推进")
    hint_lines.append('- 不要说"接下来我们看第几个问题"这类暴露教学计划的话')
    hint_lines.append("- 用追问、举例、对比等方式引导，让学生主动发现自己的理解偏差")
    hint_lines.append("- 确认学生对当前知识点真正理解后，再自然过渡到下一个")
    hint_lines.append("</教学参考>")

    return "\n".join(hint_lines)


def convert_simulation_to_train(
    sim_result_path: str,
    output_path: str,
    domain_policy: str,
    db,
    tools_schema: list,
    min_reward: float = 0.6,
):
    """
    将 simulation 结果转换为训练数据。
    只保留 reward >= min_reward 的轨迹。
    训练数据的 system prompt 不含 hint。
    """
    with open(sim_result_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build task info map from result file
    task_info_map = {}
    if "tasks" in data:
        for task in data["tasks"]:
            task_id = task.get("id")
            known_info = (
                task.get("user_scenario", {})
                .get("instructions", {})
                .get("known_info", "")
            )
            task_info_map[task_id] = known_info

    simulations = data.get("simulations", [])
    train_data = []

    for sim in simulations:
        # 过滤低分轨迹
        reward_info = sim.get("reward_info")
        if reward_info:
            reward = reward_info.get("reward", 0)
            if reward < min_reward:
                continue

        task_id = sim.get("task_id")
        known_info = task_info_map.get(task_id, "")

        # Get passage from DB
        passage = ""
        task_data = db.tasks.get(task_id)
        if task_data and task_data.passages:
            passage = next(iter(task_data.passages.values()))

        # 构建不含 hint 的 policy
        current_policy = domain_policy
        if passage:
            current_policy = current_policy + f"\n\n<passage>\n{passage}\n</passage>"

        passage_block = ""  # passage 已在 policy 中
        question_block = (
            "" if not known_info else f"\n<question>\n{known_info}\n</question>"
        )

        system_content = TRAIN_SYSTEM_PROMPT_TEMPLATE.format(
            instruction=TRAIN_SYSTEM_INSTRUCTION,
            policy=current_policy,
            passage_block=passage_block,
            question_block=question_block,
        ).strip()

        conversations = [{"role": "system", "content": system_content}]

        messages = sim.get("messages", [])
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")

            # Stop at user simulator meta messages
            if content and "作为用户模拟器" in content:
                break

            # Filter out tool outputs triggered by user
            if role == "tool" and msg.get("requestor") == "user":
                continue

            # Only assistant can have tool_calls
            if role != "assistant":
                tool_calls = None

            # Handle tool calls for assistant
            if role == "assistant" and tool_calls:
                tool_calls_str = json.dumps(tool_calls, ensure_ascii=False)
                if content:
                    content = f"{content}\n{tool_calls_str}"
                else:
                    content = tool_calls_str

            # Skip empty messages
            if not content:
                continue

            conversations.append({"role": role, "content": content})

        # 至少有 system + user + assistant 才有意义
        if len(conversations) >= 3:
            train_data.append({"conversations": conversations, "tools": tools_schema})

    # Write output
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"转换完成: {len(train_data)}/{len(simulations)} 条轨迹 (reward >= {min_reward})。保存至 {output_path}")
    return train_data


def run_gen_train(args):
    """
    主入口：带 hint 运行 simulation，然后自动转换为训练数据。
    使用训练专用数据集（db-train.json, tasks-train.json, split_tasks-train.json），
    与评测数据集完全分离。
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from tau2.data_model.simulation import RunConfig
    from tau2.domains.edu.data_model import get_db, EduDB
    from tau2.domains.edu.tools import EduAssistantTools
    from tau2.domains.edu.utils import EDU_DATA_DIR, EDU_POLICY_PATH
    from tau2.environment.toolkit import get_tool_signatures
    from tau2.run import run_domain
    from tau2.data_model.tasks import Task

    # ===== 使用训练专用数据文件 =====
    TRAIN_DB_PATH = EDU_DATA_DIR / "db-train.json"
    TRAIN_TASKS_PATH = EDU_DATA_DIR / "tasks-train.json"
    TRAIN_SPLIT_TASKS_PATH = EDU_DATA_DIR / "split_tasks-train.json"

    if not TRAIN_DB_PATH.exists():
        print(f"Error: 训练 DB 文件不存在: {TRAIN_DB_PATH}")
        return
    if not TRAIN_TASKS_PATH.exists():
        print(f"Error: 训练 tasks 文件不存在: {TRAIN_TASKS_PATH}")
        return

    # Load training DB
    db = EduDB.load(str(TRAIN_DB_PATH))
    print(f"加载训练 DB: {TRAIN_DB_PATH} ({len(db.tasks)} tasks)")

    # Load training tasks
    import json as _json
    with open(TRAIN_TASKS_PATH, "r", encoding="utf-8") as f:
        raw_tasks = _json.load(f)
    tasks = [Task.model_validate(t) for t in raw_tasks]

    # Apply split filter if split_tasks-train exists
    if TRAIN_SPLIT_TASKS_PATH.exists():
        with open(TRAIN_SPLIT_TASKS_PATH, "r", encoding="utf-8") as f:
            splits = _json.load(f)
        split_name = args.task_split_name or "base"
        if split_name in splits:
            valid_ids = set(splits[split_name])
            tasks = [t for t in tasks if t.id in valid_ids]
            print(f"应用 split '{split_name}': {len(tasks)} tasks")

    # Apply task_ids filter
    if args.task_ids:
        task_id_set = set(args.task_ids)
        tasks = [t for t in tasks if t.id in task_id_set]

    # Apply num_tasks limit
    if args.num_tasks:
        tasks = tasks[:args.num_tasks]

    print(f"最终 tasks 数量: {len(tasks)}")

    # Read domain policy
    with open(EDU_POLICY_PATH, "r", encoding="utf-8") as f:
        domain_policy = f.read().strip()

    # Build tools schema (for training data, exclude get_passage)
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
                "parameters": sig.params,
            },
        }
        tools_schema.append(tool_def)

    # Build hint map: task_id -> hint text
    hint_map = {}
    for task in tasks:
        hint = build_hint_for_task(db, task)
        hint_map[task.id] = hint

    # policy_modifier: inject hint into policy for each task
    def policy_modifier(policy: str, task: Task) -> str:
        hint = hint_map.get(task.id, "")
        if hint:
            return policy + hint
        return policy

    # ===== 临时替换 registry 中的 task loader 使其加载训练数据 =====
    from tau2.registry import registry

    def _train_task_loader(task_split_name=None):
        return tasks

    original_task_loader = registry._tasks["edu"]
    registry._tasks["edu"] = _train_task_loader

    # 临时替换 DB 加载，让 environment 使用训练 DB
    from tau2.domains.edu import environment as edu_env_module
    original_get_db = edu_env_module.get_db
    edu_env_module.get_db = lambda: EduDB.load(str(TRAIN_DB_PATH))

    try:
        # Build RunConfig
        config = RunConfig(
            domain="edu",
            task_set_name="edu",
            task_split_name=None,  # 已经手动过滤了
            task_ids=[t.id for t in tasks],
            num_tasks=None,
            agent=args.agent,
            llm_agent=args.agent_llm,
            llm_args_agent=args.agent_llm_args,
            user=args.user,
            llm_user=args.user_llm,
            llm_args_user=args.user_llm_args,
            num_trials=args.num_trials,
            max_steps=args.max_steps,
            max_errors=args.max_errors,
            save_to=args.save_to,
            max_concurrency=args.max_concurrency,
            seed=args.seed,
            log_level=args.log_level,
            enforce_communication_protocol=args.enforce_communication_protocol,
        )

        # Run simulation with hints
        print("=" * 60)
        print("第 1 步: 带教学提示运行 simulation（训练数据集）...")
        print("=" * 60)
        results = run_domain(config, policy_modifier=policy_modifier, inject_passage=True)
    finally:
        # 恢复原始 registry 和 DB 加载
        registry._tasks["edu"] = original_task_loader
        edu_env_module.get_db = original_get_db

    # Find the saved simulation file
    from tau2.utils.utils import DATA_DIR
    if args.save_to:
        sim_path = DATA_DIR / "simulations" / f"{args.save_to}.json"
    else:
        # Find latest file matching pattern
        sim_dir = DATA_DIR / "simulations"
        sim_files = sorted(sim_dir.glob("*_edu_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        sim_path = sim_files[0] if sim_files else None

    if sim_path is None or not sim_path.exists():
        print("Error: 未找到 simulation 结果文件")
        return

    # Convert to training data
    print("\n" + "=" * 60)
    print("第 2 步: 转换为训练数据（去除 hint）...")
    print("=" * 60)

    output_path = args.output if hasattr(args, "output") and args.output else str(
        DATA_DIR / "train" / f"train-{args.agent_llm.replace('/', '_')}.jsonl"
    )

    convert_simulation_to_train(
        sim_result_path=str(sim_path),
        output_path=output_path,
        domain_policy=domain_policy,
        db=db,
        tools_schema=tools_schema,
        min_reward=args.min_reward if hasattr(args, "min_reward") else 0.6,
    )

    print("\n" + "=" * 60)
    print("全部完成！")
    print(f"  Simulation 文件: {sim_path}")
    print(f"  训练数据文件:    {output_path}")
    print("=" * 60)
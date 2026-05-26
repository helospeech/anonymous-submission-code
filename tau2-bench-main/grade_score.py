#!/usr/bin/env python3
"""从 simulation JSON 中提取各学段(小学/初中/高中)的 pass@1 和 avg_reward"""
import json
import sys
import os

def is_successful(reward):
    return (1 - 1e-6) <= reward <= (1 + 1e-6)

def main():
    if len(sys.argv) < 2:
        print("用法: python3 grade_score.py <simulation.json> [mapping.json]", file=sys.stderr)
        sys.exit(1)

    sim_file = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mapping_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(script_dir, "task_grade_mapping.json")

    # 加载学段映射
    with open(mapping_file, "r", encoding="utf-8") as f:
        grade_mapping = json.load(f)

    # 构建 task_id -> 学段 的反向映射
    task_to_grade = {}
    for grade, task_ids in grade_mapping.items():
        for tid in task_ids:
            task_to_grade[tid] = grade

    # 加载 simulation 结果
    with open(sim_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    simulations = data.get("simulations", [])
    if not simulations:
        print("N/A|N/A|N/A|N/A|N/A|N/A")
        return

    # 按 task_id 收集 reward（可能每个 task 有多个 trial）
    task_rewards = {}
    for sim in simulations:
        tid = sim.get("task_id", "")
        reward_info = sim.get("reward_info", {})
        reward = reward_info.get("reward", None)
        if reward is None:
            reward = sim.get("reward", None)
        if reward is not None:
            if tid not in task_rewards:
                task_rewards[tid] = []
            task_rewards[tid].append(float(reward))

    # 按学段分组计算 avg_reward 和 pass@1
    grade_rewards = {"小学": [], "初中": [], "高中": []}
    grade_pass = {"小学": [], "初中": [], "高中": []}

    for tid, rewards in task_rewards.items():
        grade = task_to_grade.get(tid, None)
        if grade and grade in grade_rewards:
            avg_r = sum(rewards) / len(rewards)
            grade_rewards[grade].append(avg_r)
            # pass@1: 对每个task，有至少一个trial成功则为1
            task_pass = 1.0 if any(is_successful(r) for r in rewards) else 0.0
            grade_pass[grade].append(task_pass)

    # 输出格式: 小学avg|小学pass1|初中avg|初中pass1|高中avg|高中pass1
    parts = []
    for grade in ["小学", "初中", "高中"]:
        rlist = grade_rewards[grade]
        plist = grade_pass[grade]
        if rlist:
            avg_val = sum(rlist) / len(rlist)
            pass_val = sum(plist) / len(plist)
            parts.append(f"{avg_val:.4f}")
            parts.append(f"{pass_val:.4f}")
        else:
            parts.append("N/A")
            parts.append("N/A")
    print("|".join(parts))

if __name__ == "__main__":
    main()
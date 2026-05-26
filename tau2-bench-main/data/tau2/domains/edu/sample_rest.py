#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
排除已抽样的100条，保存剩余的全部数据到新文件
"""

import os
import json
from typing import Any, Set

def load_json(file_path: str) -> Any:
    """加载 JSON 文件"""
    if not os.path.exists(file_path):
        print(f"⚠️ 找不到文件: {os.path.basename(file_path)}")
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data: Any, file_path: str) -> None:
    """保存 JSON 文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {os.path.basename(file_path)}")

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. 读取合并后的完整数据
    db_file = os.path.join(current_dir, "db_merged.json")
    tasks_file = os.path.join(current_dir, "tasks_merged.json")

    # 2. 读取已抽取的100条ID
    split_file = os.path.join(current_dir, "split_tasks.json")

    print("🚀 开始读取数据文件...")
    db_data = load_json(db_file)
    tasks_data = load_json(tasks_file)
    split_data = load_json(split_file)

    if not db_data or not tasks_data or not split_data:
        print("❌ 缺少必要文件，无法继续。")
        return

    # 已抽取的100条ID
    sampled_ids: Set[str] = set(split_data.get("base", []))
    print(f"📊 已抽取的ID数量: {len(sampled_ids)}")

    # 3. 获取 db 和 tasks 的共有 ID
    db_ids: Set[str] = set()
    if isinstance(db_data, dict) and "tasks" in db_data:
        db_ids = set(db_data["tasks"].keys())

    tasks_ids: Set[str] = set()
    if isinstance(tasks_data, list):
        for item in tasks_data:
            if isinstance(item, dict) and "id" in item:
                tasks_ids.add(str(item["id"]))

    common_ids = db_ids & tasks_ids
    print(f"📊 db 包含 {len(db_ids)} 个 ID, tasks 包含 {len(tasks_ids)} 个 ID")
    print(f"🔗 共有 ID 数量: {len(common_ids)}")

    # 4. 排除已抽取的ID，得到剩余ID
    rest_ids = common_ids - sampled_ids
    rest_ids_set = set(rest_ids)
    print(f"🔢 排除已抽取后，剩余 ID 数量: {len(rest_ids)}")

    if not rest_ids:
        print("❌ 没有剩余的数据可以保存。")
        return

    # 5. 根据剩余ID重建数据结构
    # 重建 db 样本
    db_rest = {"tasks": {}}
    for k, v in db_data["tasks"].items():
        if str(k) in rest_ids_set:
            db_rest["tasks"][k] = v

    # 重建 tasks 样本
    tasks_rest = []
    for item in tasks_data:
        if isinstance(item, dict) and str(item.get("id")) in rest_ids_set:
            tasks_rest.append(item)

    # 生成 split_tasks
    split_rest = {"base": sorted(list(rest_ids))}

    # 6. 保存到新文件
    print("\n💾 正在保存剩余数据...")

    db_out = os.path.join(current_dir, "db_rest.json")
    tasks_out = os.path.join(current_dir, "tasks_rest.json")
    split_out = os.path.join(current_dir, "split_tasks_rest.json")

    save_json(db_rest, db_out)
    save_json(tasks_rest, tasks_out)
    save_json(split_rest, split_out)

    print(f"\n🎉 完成！共保存了 {len(rest_ids)} 条剩余数据。")
    print(f"   db_rest.json: {len(db_rest['tasks'])} 条")
    print(f"   tasks_rest.json: {len(tasks_rest)} 条")
    print(f"   split_tasks_rest.json: {len(split_rest['base'])} 个ID")

if __name__ == "__main__":
    main()
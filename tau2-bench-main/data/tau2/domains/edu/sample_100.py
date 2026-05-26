#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 抽样与数据补全脚本
基于 db 和 tasks 的共有 ID 抽取 100 条数据，并自动生成对应的 split_tasks.json
"""

import os
import json
import random
from typing import Dict, List, Any, Set

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
    
    # 1. 定义输入文件路径
    db_file = os.path.join(current_dir, "db_merged.json")
    tasks_file = os.path.join(current_dir, "tasks_merged.json")
    
    print("🚀 开始读取 db 和 tasks 数据文件...")
    db_data = load_json(db_file)
    tasks_data = load_json(tasks_file)
    
    if not db_data or not tasks_data:
        print("❌ 缺少 db_merged.json 或 tasks_merged.json，无法进行抽样。")
        return

    print("\n🔍 正在解析并提取关联 ID...")
    
    # 2. 提取 db.json 中的 ID (tasks 下的键)
    db_ids: Set[str] = set()
    if isinstance(db_data, dict) and "tasks" in db_data:
        db_ids = set(db_data["tasks"].keys())
        
    # 3. 提取 tasks.json 中的 ID (列表对象中的 id 字段)
    tasks_ids: Set[str] = set()
    if isinstance(tasks_data, list):
        for item in tasks_data:
            if isinstance(item, dict) and "id" in item:
                tasks_ids.add(str(item["id"]))

    # 4. 取两个文件的 ID 交集
    common_ids = list(db_ids & tasks_ids)
    print(f"📊 统计: db 包含 {len(db_ids)} 个 ID, tasks 包含 {len(tasks_ids)} 个 ID")
    print(f"🔗 找到完全对应的共有 ID 数量: {len(common_ids)}")
    
    if not common_ids:
        print("❌ 没有找到匹配的共有 ID，无法抽样。请检查数据格式是否正确。")
        return

    # 5. 随机抽取 100 个 ID (如果总数不足 100，则全量抽取)
    sample_size = min(100, len(common_ids))
    sampled_ids = random.sample(common_ids, sample_size)
    sampled_ids_set = set(sampled_ids) # 用于快速查找
    print(f"🎲 成功随机抽取 {sample_size} 个 ID，正在生成样本数据...")

    # 6. 根据抽中的 ID 重建数据结构
    
    # 重建 db 样本 (保留原有的 {"tasks": {...}} 结构)
    db_sample = {"tasks": {}}
    for k, v in db_data["tasks"].items():
        if str(k) in sampled_ids_set:
            db_sample["tasks"][k] = v
            
    # 重建 tasks 样本 (保留原有的 [...] 列表结构)
    tasks_sample = []
    for item in tasks_data:
        if isinstance(item, dict) and str(item.get("id")) in sampled_ids_set:
            tasks_sample.append(item)
            
    # 自动生成全新的 split_tasks 样本 (结构: {"base": ["id1", "id2", ...]})
    # 注意：这里直接使用 sampled_ids 列表，保持抽取的随机顺序
    split_sample = {"base": sampled_ids}

    # 7. 保存结果文件
    print("\n💾 正在保存抽样结果...")
    
    # 定义输出文件名 (加上 _sample_100 后缀以示区分)
    db_out = os.path.join(current_dir, "db.json")
    tasks_out = os.path.join(current_dir, "tasks.json")
    split_out = os.path.join(current_dir, "split_tasks.json")
    
    save_json(db_sample, db_out)
    save_json(tasks_sample, tasks_out)
    save_json(split_sample, split_out)
    
    print(f"\n🎉 抽样与补全完成！共生成了 {sample_size} 条完全对齐的数据。")

if __name__ == "__main__":
    main()

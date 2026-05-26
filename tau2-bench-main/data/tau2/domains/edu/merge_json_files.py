#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并JSON文件脚本 (含数据条数统计 & 深度去重)
将指定目录下按类别划分的JSON文件合并，统计数据量，并去除完全重复的条目。
"""

import os
import json
import glob
from typing import Dict, List, Any, Union

def get_data_signature(data: Any) -> str:
    """
    生成数据的唯一字符串签名，用于去重比较。
    通过 sort_keys=True 保证即使字典中键的顺序不同，只要内容相同也会生成相同的签名。
    """
    if isinstance(data, (dict, list)):
        return json.dumps(data, sort_keys=True, ensure_ascii=False)
    return str(data)

def deduplicate_list(data_list: List[Any]) -> List[Any]:
    """对列表中的元素进行深度去重"""
    seen_signatures = set()
    unique_list = []
    
    for item in data_list:
        signature = get_data_signature(item)
        if signature not in seen_signatures:
            seen_signatures.add(signature)
            unique_list.append(item)
            
    return unique_list

def deduplicate_dict(data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """对字典中的值进行深度去重（保留第一个出现的完全不重复的Value）"""
    seen_signatures = set()
    unique_dict = {}
    
    for key, value in data_dict.items():
        signature = get_data_signature(value)
        if signature not in seen_signatures:
            seen_signatures.add(signature)
            unique_dict[key] = value
            
    return unique_dict

def get_data_count(category: str, data: Any) -> int:
    """计算当前数据结构中的条数"""
    if not data:
        return 0
    if category == "db":
        return len(data.get("tasks", {}))
    elif category == "tasks":
        return len(data) if isinstance(data, list) else 0
    elif category == "split_tasks":
        if isinstance(data, dict) and "tasks" in data:
            return len(data["tasks"])
        elif isinstance(data, dict):
            return len(data.keys())
            
    if isinstance(data, dict):
        return len(data.keys())
    elif isinstance(data, list):
        return len(data)
    return 0

def merge_json_files(directory: str) -> None:
    """合并目录中的JSON文件并去重"""
    json_files = glob.glob(os.path.join(directory, "*.json"))
    categories = {}
    
    for file_path in json_files:
        filename = os.path.basename(file_path)
        if filename == "merge_json_files.py":
            continue
            
        if filename.startswith("db"):
            category = "db"
        elif filename.startswith("tasks"):
            category = "tasks"
        elif filename.startswith("split_tasks"):
            category = "split_tasks"
        else:
            category = "other"
            
        if category not in categories:
            categories[category] = []
        categories[category].append(file_path)
    
    for category, file_list in categories.items():
        if category == "other":
            continue
            
        print(f"\n📁 正在合并 [{category}] 类别的文件...")
        
        # 1. 合并数据
        merged_data = merge_category_files(file_list, category)
        raw_count = get_data_count(category, merged_data)
        
        # 2. 执行去重
        deduplicated_data = apply_deduplication(category, merged_data)
        final_count = get_data_count(category, deduplicated_data)
        removed_count = raw_count - final_count
        
        # 3. 保存文件
        output_filename = f"{category}_merged.json"
        output_path = os.path.join(directory, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(deduplicated_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已保存合并文件: {output_filename}")
        print(f"📊 统计: 共读取 {raw_count} 条数据")
        if removed_count > 0:
            print(f"🗑️  去重: 移除了 {removed_count} 条完全重复的数据")
        else:
            print("✨ 去重: 未发现重复数据")
        print(f"🎯 最终: 包含 {final_count} 条独立数据")
        print("-" * 40)

def apply_deduplication(category: str, data: Any) -> Any:
    """根据数据类别应用对应的去重策略"""
    if category == "db" and "tasks" in data:
        data["tasks"] = deduplicate_dict(data["tasks"])
        return data
    elif category == "tasks" and isinstance(data, list):
        return deduplicate_list(data)
    elif category == "split_tasks":
        if isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
            data["tasks"] = deduplicate_list(data["tasks"])
        elif isinstance(data, dict):
            data = deduplicate_dict(data)
        return data
    return data

def merge_category_files(file_list: List[str], category: str) -> Union[Dict, List]:
    """路由到对应的合并函数"""
    if category == "db":
        return merge_db_files(file_list)
    elif category == "tasks":
        return merge_tasks_files(file_list)
    elif category == "split_tasks":
        return merge_split_tasks_files(file_list)
    else:
        return merge_generic_files(file_list)

def merge_db_files(file_list: List[str]) -> Dict[str, Any]:
    merged_tasks = {}
    for file_path in file_list:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'tasks' in data:
                print(f"  📄 读取: {os.path.basename(file_path)} ({len(data['tasks'])} 条)")
                merged_tasks.update(data['tasks'])
        except Exception as e:
            print(f"  ❌ 出错: {e}")
    return {"tasks": merged_tasks}

def merge_tasks_files(file_list: List[str]) -> List[Dict[str, Any]]:
    merged_tasks = []
    for file_path in file_list:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                print(f"  📄 读取: {os.path.basename(file_path)} ({len(data)} 条)")
                merged_tasks.extend(data)
        except Exception as e:
            print(f"  ❌ 出错: {e}")
    return merged_tasks

def merge_split_tasks_files(file_list: List[str]) -> Dict[str, Any]:
    merged_data = {}
    for file_path in file_list:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                print(f"  📄 读取: {os.path.basename(file_path)} ({len(data)} 个键值对)")
                merged_data.update(data)
            elif isinstance(data, list):
                print(f"  📄 读取: {os.path.basename(file_path)} ({len(data)} 条)")
                if 'tasks' not in merged_data:
                    merged_data['tasks'] = []
                merged_data['tasks'].extend(data)
        except Exception as e:
            print(f"  ❌ 出错: {e}")
    return merged_data

def merge_generic_files(file_list: List[str]) -> Dict[str, Any]:
    merged_data = {}
    for file_path in file_list:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged_data.update(data)
        except Exception as e:
            print(f"  ❌ 出错: {e}")
    return merged_data

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print("🚀 开始合并、统计并去重 JSON 文件...")
    print(f"📍 目标目录: {current_dir}")
    print("=" * 40)
    
    merge_json_files(current_dir)
    
    print("🎉 所有任务已完成!")

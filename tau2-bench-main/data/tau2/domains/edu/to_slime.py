import json
import os
import random

# 定义容器内的数据路径（请根据实际挂载/存放的路径修改）
data_dir = os.path.dirname(os.path.abspath(__file__))
input_path = os.path.join(data_dir, "tasks.json")
out_train = os.path.join(data_dir, "train_tasks.jsonl")
out_dev = os.path.join(data_dir, "dev_tasks.jsonl")

# 确保目录存在
if not os.path.exists(data_dir):
    print(f"Error: Directory {data_dir} does not exist in container!")
    exit(1)

with open(input_path, "r", encoding="utf-8") as f:
    tasks = json.load(f)

# 打乱数据集以保证验证集划分的随机性（固定随机种子以保证每次生成的 index 一致）
random.seed(42)
random.shuffle(tasks)

# 假设留下最后20条作为验证集，其余作为训练集
train_tasks, dev_tasks = tasks[:-20], tasks[-20:]

for out_path, data in [(out_train, train_tasks), (out_dev, dev_tasks)]:
    with open(out_path, "w", encoding="utf-8") as f:
        for i, t in enumerate(data):
            f.write(json.dumps({"index": i, "task_id": t["id"]}) + "\n")
print("✅ .jsonl data generated successfully in container!")
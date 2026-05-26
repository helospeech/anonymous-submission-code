# 导入必要的库
import os
import requests  # 用于发送HTTP请求
import json      # 用于处理JSON数据

# API配置
url = os.getenv("API_URL", "https://openrouter.ai/api/v1/chat/completions")
headers = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {os.getenv("API_KEY", "")}',
    'Content-Type': 'application/json'
}

# 构建请求数据
payload = json.dumps({
    "model": "qwen-max-latest",                    # 使用的AI模型
    "messages": [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "周树人和鲁迅是兄弟吗？"
        }
    ]
})

# 发送POST请求到API
response = requests.post(url, headers=headers, data=payload)

# 打印格式化的JSON响应结果
response_json = response.json()
print(json.dumps(response_json, indent=2, ensure_ascii=False))
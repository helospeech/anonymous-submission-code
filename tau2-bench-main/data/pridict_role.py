import json
import os
import asyncio
import time
import random
import logging
import httpx
from pathlib import Path
from typing import List, Dict, Optional, Any, AsyncGenerator
from dataclasses import dataclass, field
from collections import deque

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("async_caller")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ============ 严格滑动窗口限速器 ============
class StrictRateLimiter:
    def __init__(self, max_calls: int, period: float = 1.0):
        self.max_calls = max_calls
        self.period = period
        self._calls = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait_time = self.period - (now - self._calls[0])
            if wait_time > 0:
                await asyncio.sleep(wait_time)

# ============ 数据结构 ============
@dataclass
class ModelConfig:
    name: str = "gpt-5"
    api_url: str = os.getenv("API_URL", "https://openrouter.ai/api/v1/chat/completions")
    qps: int = 20
    temperature: float = 1.0
    max_tokens: int = 16384
    stream: bool = False
    top_p: float = 1.0

@dataclass
class PromptMeta:
    index: int
    task_id: str
    true_label: str
    messages: List[Dict[str, str]]
    raw_data: dict

@dataclass
class Stats:
    success: int = 0
    failed: int = 0
    retried: int = 0
    total_processed: int = 0
    start_time: float = field(default_factory=time.time)
    latencies: List[float] = field(default_factory=list)

def simplify_trajectory(messages):
    """
    精简对话轨迹，只保留 user 和 assistant 的实际内容。
    对于过长的文本（如老师发送的大段课文）进行截断处理，保留头尾各150字。
    """
    dialogue = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()
        
        # 我们只关心实际对话，过滤掉空内容或者工具的raw_data
        if role in ["user", "assistant"] and content:
            # 过滤掉模拟器系统指令
            if "作为用户模拟器，检查一下上面的对话" in content:
                continue
                
            if len(content) > 300:
                content = content[:150] + "\n...[省略部分内容]...\n" + content[-150:]
            dialogue.append(f"[{role}]: {content}")
            
    return "\n".join(dialogue)

# ============ 主逻辑类 ============
class AsyncPromptCaller:
    def __init__(self,
                 input_file: str,
                 output_file: str,
                 api_key: str,
                 model_config: Optional[ModelConfig] = None,
                 qps: int = 20,
                 max_retries: int = 3,
                 retry_backoff_base: float = 0.8):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.api_key = api_key
        self.model_config = model_config or ModelConfig()
        self.rate_limiter = StrictRateLimiter(max_calls=qps, period=1.0)
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.stats = Stats()
        self.processed_indices = set()
        self.current_active = 0
        self.result_queue = asyncio.Queue()
        self._writer_task = None
        
        limits = httpx.Limits(max_connections=1000, max_keepalive_connections=600, keepalive_expiry=30.0)
        self.client = httpx.AsyncClient(
            limits=limits,
            http2=False,
            timeout=httpx.Timeout(300.0, read=120.0, connect=60.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )

    def load_existing_results(self):
        if not self.output_file.exists():
            return
        loaded_count = 0
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        line = line.strip()
                        if not line: continue
                        data = json.loads(line)
                        if data.get("success"):
                            idx = data.get("index")
                            if idx is not None:
                                self.processed_indices.add(idx)
                                loaded_count += 1
                    except Exception: continue
        except Exception as e:
            logger.warning(f"加载已有结果出错: {e}")
        logger.info(f"已加载 {loaded_count} 条历史成功记录")

    async def prompt_generator(self, limit: Optional[int] = None) -> AsyncGenerator[PromptMeta, None]:
        with open(self.input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        simulations = data.get("simulations", [])
        yielded_count = 0
        
        for i, sim in enumerate(simulations):
            if limit and yielded_count >= limit:
                break
                
            if i in self.processed_indices:
                continue
                
            task_id = sim.get("task_id", "")
            messages = sim.get("messages", [])
            
            true_label = None
            for label in ["mischievous", "anxious", "imaginative", "refusing"]:
                if label in task_id:
                    true_label = label
                    break
                    
            if not true_label:
                continue
                
            dialogue = simplify_trajectory(messages)
            if not dialogue:
                continue
                
            prompt = f"""你是一个专业的教育心理学和学生行为分析专家。
下面是一段一对一语文辅导课堂的师生对话记录。请你分析其中学生（user）的表现，判断该学生扮演的是以下哪一种角色设定：

1. mischievous: 调皮捣蛋，注意力不集中，喜欢从字面意思理解，将内容联系到吃玩等日常生活，表现出抗拒或漫不经心。
2. anxious: 焦虑，追求完美，害怕犯错，总是过度解读寻找标准答案或考点，紧张不安。
3. imaginative: 想象力极其丰富，沉迷科幻或电子游戏，用科幻/游戏逻辑来解读课文，逻辑跳跃，经常问奇怪具体的“科学”问题。
4. refusing: 被动且固执，消极对抗，拒绝主动说明哪里不懂，常回答“不知道”或沉默，只有老师讲解后才承认理解。

对话记录如下：
{dialogue}

请仅输出该学生的角色英文名（必须且只能是 mischievous, anxious, imaginative, refusing 中的一个），不要输出任何其他内容。"""

            yield PromptMeta(
                index=i,
                task_id=task_id,
                true_label=true_label,
                messages=[{"role": "user", "content": prompt}],
                raw_data=sim
            )
            yielded_count += 1

    async def _writer(self):
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            item = await self.result_queue.get()
            if item is None:
                self.result_queue.task_done()
                break
            try:
                with open(self.output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"写入结果失败: {e}")
            finally:
                self.result_queue.task_done()

    async def call_one(self, meta: PromptMeta):
        self.current_active += 1
        try:
            payload = {
                "messages": meta.messages,
                "model": self.model_config.name,
                "stream": self.model_config.stream,
                "temperature": self.model_config.temperature,
                "max_tokens": self.model_config.max_tokens,
            }
            
            for attempt in range(self.max_retries):
                try:
                    resp = await self.client.post(self.model_config.api_url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"].strip().lower()
                        
                        pred_label = "unknown"
                        for label in ["mischievous", "anxious", "imaginative", "refusing"]:
                            if label in content:
                                pred_label = label
                                break
                                
                        self.stats.success += 1
                        await self.result_queue.put({
                            "success": True,
                            "index": meta.index,
                            "task_id": meta.task_id,
                            "true_label": meta.true_label,
                            "pred_label": pred_label,
                            "response": content
                        })
                        return
                    else:
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep((self.retry_backoff_base ** attempt) + random.uniform(0, 0.5))
                            continue
                        raise RuntimeError(f"API Error {resp.status_code}: {resp.text[:200]}")
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep((self.retry_backoff_base ** attempt) + random.uniform(0, 0.5))
                        continue
                    self.stats.failed += 1
                    await self.result_queue.put({
                        "success": False,
                        "index": meta.index,
                        "task_id": meta.task_id,
                        "error": str(e)
                    })
                    return
        finally:
            self.current_active -= 1
            self.stats.total_processed += 1
            if self.stats.total_processed % 50 == 0:
                logger.info(f"✅ 进度: {self.stats.total_processed} | 并发: {self.current_active} | 成功: {self.stats.success}")

    async def run(self):
        self.load_existing_results()
        self._writer_task = asyncio.create_task(self._writer())
        background_tasks = set()
        
        logger.info(f"开始并发处理文件...")
        async for meta in self.prompt_generator():
            await self.rate_limiter.acquire()
            task = asyncio.create_task(self.call_one(meta))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

        if background_tasks:
            await asyncio.gather(*background_tasks)
            
        await self.result_queue.put(None)
        await self.result_queue.join()
        await self._writer_task

    async def close(self):
        await self.client.aclose()

async def async_main():
    input_file = os.path.join(os.path.dirname(__file__), "simulations/20260112_235037_edu_llm_agent_DeepSeek-V3.2_user_simulator_qwen-max-latest.json")
    output_file = os.path.join(os.path.dirname(__file__), "classification_results.jsonl")
    
    # 按照 example_call.py 的配置
    api_key = os.getenv("API_KEY", "")
    qps = 5
    model_name = "gpt-5" # 或者换成 qwen-max-latest，可按需修改
    
    caller = AsyncPromptCaller(
        input_file=input_file,
        output_file=output_file,
        api_key=api_key,
        model_config=ModelConfig(qps=qps, name=model_name),
        qps=qps
    )
    
    try:
        await caller.run()
    finally:
        await caller.close()
        
    # 读取并计算分数
    y_true = []
    y_pred = []
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                data = json.loads(line)
                if data.get("success"):
                    y_true.append(data.get("true_label"))
                    y_pred.append(data.get("pred_label"))
                    
    if y_true:
        from sklearn.metrics import classification_report
        labels = ["mischievous", "anxious", "imaginative", "refusing"]
        print("\n================ 分类报告 (P/R/F1) ================\n")
        print(classification_report(y_true, y_pred, target_names=labels, labels=labels, zero_division=0))
        print("====================================================\n")

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
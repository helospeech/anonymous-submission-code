#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用说明:
这是一个异步并发 + 重试 + 纯 QPS 控制 + 流式读取 + 并发监控 的版本。

修改点：
1. 移除了 max_concurrency (Semaphore) 限制。
2. 任务的生成速率完全由 QPS (StrictRateLimiter) 控制。
3. 实际并发数将由 (QPS * 平均响应时间) 动态决定。
4. 【新增】在 run 循环中增加了实时发送速率 (Send QPS) 的打印监控。
5. 【本次修改】读取逻辑更新：Prompt 内容纯净，仅包含 conversations[1]['value']，移除了所有固定指令。
"""

import asyncio
import json
import time
import random
from pathlib import Path
from typing import List, Dict, Optional, Any, AsyncGenerator
import logging
import httpx
from httpx import Limits, Timeout
import traceback
from dataclasses import dataclass, field
from collections import deque
import os

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("prompt_calling_stream.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("async_caller")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ============ 严格滑动窗口限速器 ============
class StrictRateLimiter:
    """
    严格滑动窗口限速：确保任意滚动 period (默认1秒) 内调用次数 <= max_calls。
    """
    def __init__(self, max_calls: int, period: float = 1.0):
        self.max_calls = max_calls
        self.period = period
        self._calls = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                # 清理窗口外的记录
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
    top_p: float = 0.001

@dataclass
class PromptMeta:
    index: int
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

    def success_rate(self):
        total = self.success + self.failed
        return (self.success / total) if total else 0.0

    def avg_latency(self):
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0


# ============ 主逻辑类 ============
class AsyncPromptCaller:
    def __init__(self,
                 input_file: str,
                 output_file: str,
                 api_key: str,
                 model_config: Optional[ModelConfig] = None,
                 qps: int = 2,
                 max_retries: int = 3,
                 retry_backoff_base: float = 0.8):
        if qps <= 0:
            raise ValueError("QPS 必须 > 0")
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.api_key = api_key
        self.model_config = model_config or ModelConfig()

        # 移除 max_concurrency 属性
        self.rate_limiter = StrictRateLimiter(max_calls=qps, period=1.0)
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base

        self.stats = Stats()
        
        # 【新增】记录已完成的 index
        self.processed_indices = set()

        # 【新增】当前活跃并发计数 (仅用于显示，不用于控制)
        self.current_active = 0
        
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        limits = httpx.Limits(
            max_connections=10000, 
            max_keepalive_connections=6000,  
            keepalive_expiry=30.0          
        )
        self.client = httpx.AsyncClient(
            limits=limits,
            http2=False,
            timeout=httpx.Timeout(3000.0, read=300.0, connect=300.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )

    # ---------- 加载已有结果 ----------
    def load_existing_results(self):
        if not self.output_file.exists():
            return
        
        logger.info(f"正在加载已有结果: {self.output_file}")
        loaded_count = 0
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("success"):
                            idx = data.get("index")
                            if idx is not None:
                                self.processed_indices.add(idx)
                                loaded_count += 1
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"加载已有结果出错: {e}")
            
        logger.info(f"已加载 {loaded_count} 条历史成功记录")

    # ---------- 流式读取生成器 ----------
    async def prompt_generator(self, limit: Optional[int] = None, start: int = 0) -> AsyncGenerator[PromptMeta, None]:
        """
        异步生成器：逐行读取文件，解析并 yield PromptMeta 对象。
        修改逻辑：提取 data['conversations'][1]['value'] 直接作为输入内容，不拼接任何前缀。
        """
        if not self.input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {self.input_file}")

        count = 0
        yielded_count = 0
        
        with open(self.input_file, "r", encoding="utf-8") as f:
            # 跳过前 start 行
            for _ in range(start):
                next(f, None)
                count += 1
            
            for line in f:
                if limit and yielded_count >= limit:
                    break
                
                try:
                    # 如果已经处理过，直接跳过
                    if count in self.processed_indices:
                        continue

                    line_str = line.strip()
                    if not line_str:
                        continue
                        
                    # 1. 解析 JSON
                    try:
                        data = json.loads(line_str)
                    except json.JSONDecodeError:
                        logger.warning(f"JSON 解析错误，行号: {count}")
                        continue

                    # ==========================================
                    # 修改核心逻辑：提取 conversations[1]['value']
                    # ==========================================
                    target_content = ""
                    try:
                        # 检查字段是否存在，防止报错
                        if (
                            "conversations" in data 
                            and isinstance(data["conversations"], list) 
                            and len(data["conversations"]) > 1
                        ):
                            target_content = data["conversations"][1].get("value", "")
                        else:
                            # 如果结构不匹配，打印警告并跳过
                            logger.warning(f"行号 {count}: 数据结构不满足 conversations[1]['value']，跳过。")
                            continue
                            
                    except Exception as e:
                        logger.warning(f"字段提取异常，行号 {count}: {e}")
                        continue

                    # 直接使用提取的内容，不加任何前缀
                    messages = [
                        {"role": "user", "content": str(target_content)}
                    ]
                    
                    yield PromptMeta(
                        index=count,
                        messages=messages,
                        raw_data=data
                    )
                    yielded_count += 1
                        
                except Exception as e:
                    logger.warning(f"数据处理错误，行号: {count}: {e}")
                finally:
                    count += 1
                    # 偶尔让出控制权
                    if count % 100 == 0:
                        await asyncio.sleep(0)

    # ---------- 写文件 ----------
    async def _writer(self):
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"准备写入结果文件 (Append Mode): {self.output_file}")

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

    # ---------- 单个调用 ----------
    async def call_one(self, meta: PromptMeta):
        """
        执行单个请求。
        """
        # 【计数器+1】任务开始
        self.current_active += 1
        
        try:
            overall_start = time.monotonic()
            
            payload = {
                "messages": meta.messages,
                "model": self.model_config.name,
                "stream": self.model_config.stream,
                "temperature": self.model_config.temperature,
                "max_tokens": self.model_config.max_tokens,
            }

            first_latency_recorded = False

            for attempt in range(self.max_retries):
                try:
                    resp = await self.client.post(self.model_config.api_url, json=payload)
                    status_code = resp.status_code

                    if status_code == 200:
                        data = resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            content = data["choices"][0]["message"]["content"].strip()
                        else:
                            raise ValueError(f"响应结构异常: {data}")

                        latency = time.monotonic() - overall_start
                        if not first_latency_recorded:
                            self.stats.latencies.append(latency)
                            first_latency_recorded = True
                        self.stats.success += 1

                        result = {
                            "success": True,
                            "index": meta.index,
                            "original_data": meta.raw_data,
                            "response": content,
                            "raw_response": data,
                            "status_code": status_code,
                            "latency": latency,
                            "model_used": self.model_config.name,
                            "timestamp": time.time()
                        }

                        await self.result_queue.put(result)
                        return # 成功退出

                    else:
                        error_text = resp.text
                        retriable = status_code in (429, 500, 502, 503, 504)
                        if retriable and attempt < self.max_retries - 1:
                            backoff = (self.retry_backoff_base ** attempt) + random.uniform(0, 0.5)
                            logger.warning(
                                f"[ID:{meta.index}] 请求失败 {status_code}，重试 ({attempt + 1}/{self.max_retries})，"
                                f"等待 {backoff:.2f}s"
                            )
                            self.stats.retried += 1
                            await asyncio.sleep(backoff)
                            continue
                        else:
                            raise RuntimeError(f"非成功状态码: {status_code}, 响应: {error_text[:200]}")

                except Exception as e:
                    is_last = (attempt == self.max_retries - 1)
                    if not is_last:
                        backoff = (self.retry_backoff_base ** attempt) + random.uniform(0, 0.5)
                        logger.exception(
                            f"[ID:{meta.index}] 异常: {type(e).__name__} - {repr(e)}. 重试 ({attempt + 1}/{self.max_retries})，等待 {backoff:.2f}s"
                        )
                        self.stats.retried += 1
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        latency = time.monotonic() - overall_start
                        if not first_latency_recorded:
                            self.stats.latencies.append(latency)
                            first_latency_recorded = True
                        self.stats.failed += 1

                        await self.result_queue.put({
                            "success": False,
                            "index": meta.index,
                            "original_data": meta.raw_data,
                            "error": str(e),
                            "latency": latency,
                            "timestamp": time.time()
                        })
                        return

        finally:
            # 【计数器-1】任务结束
            self.current_active -= 1
            
            self.stats.total_processed += 1
            
            # 每 50 条打印一次进度和并发情况 (这是处理完成的速度)
            if self.stats.total_processed % 50 == 0:
                elapsed = time.time() - self.stats.start_time
                avg_speed = self.stats.success / elapsed if elapsed > 0 else 0
                
                logger.info(
                    f"✅ [处理进度] 总数: {self.stats.total_processed} | "
                    f"当前并发: {self.current_active} | "
                    f"成功: {self.stats.success} | 失败: {self.stats.failed} | "
                    f"平均处理速度: {avg_speed:.2f} /s"
                )

    # ---------- 主执行 ----------
    async def run(self, start=0, limit=None):
        # 加载历史记录
        self.load_existing_results()
        
        self._writer_task = asyncio.create_task(self._writer())
        
        background_tasks = set()

        logger.info(f"开始流式处理文件: {self.input_file}")
        logger.info(f"无硬性并发限制，严格 QPS 限制: {self.model_config.qps}")

        # === 监控变量初始化 ===
        sent_count_window = 0
        last_sent_log_time = time.monotonic()
        log_interval = 1.0  # 每 1 秒打印一次发送速度

        async for meta in self.prompt_generator(limit=limit, start=start):
            # 1. 在这里进行限速
            await self.rate_limiter.acquire()
            
            # 2. 创建任务
            task = asyncio.create_task(self.call_one(meta))
            
            # 3. 记录任务引用
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

            # === 4. 【新增】实时计算发送速度 ===
            sent_count_window += 1
            now = time.monotonic()
            delta_time = now - last_sent_log_time
            
            if delta_time >= log_interval:
                current_send_qps = sent_count_window / delta_time
                logger.info(f"🚀 [发送端监控] 实时请求发出速度: {current_send_qps:.2f} req/s (Target: {self.model_config.qps})")
                
                # 重置计数器
                sent_count_window = 0
                last_sent_log_time = now

        logger.info("文件读取完毕，等待剩余任务结束...")
        if background_tasks:
            await asyncio.gather(*background_tasks)

        await self.result_queue.put(None)
        await self.result_queue.join()
        await self._writer_task

    async def close(self):
        await self.client.aclose()

    def summary(self):
        elapsed = time.time() - self.stats.start_time
        approx_qps = self.stats.success / elapsed if elapsed > 0 else 0.0
        return {
            "input_file": str(self.input_file),
            "output_file": str(self.output_file),
            "total_processed": self.stats.total_processed,
            "success": self.stats.success,
            "failed": self.stats.failed,
            "retried": self.stats.retried,
            "success_rate": f"{self.stats.success_rate():.2%}",
            "avg_latency": f"{self.stats.avg_latency():.2f}s",
            "elapsed_time": f"{elapsed:.2f}s",
            "approx_qps": f"{approx_qps:.2f}",
        }


# ============ 主入口 ============
async def main():
    # 待处理的文件列表
    input_files = [
        "./data/input_nankai.jsonl",
        "./data/input_qinghua.jsonl"
    ]

    # 通用配置
    api_key = os.getenv("API_KEY", "")
    qps = 80
    
    for input_file in input_files:
        input_path = Path(input_file)
        # 自动生成输出文件名：在原文件名后加 _scored
        output_file = input_path.with_name(f"{input_path.stem}_called.jsonl")
        
        logger.info(f"==========================================================")
        logger.info(f"正在处理文件: {input_file}")
        logger.info(f"输出文件路径: {output_file}")
        logger.info(f"==========================================================")

        caller = AsyncPromptCaller(
            input_file=str(input_path),
            output_file=str(output_file),
            api_key=api_key,
            model_config=ModelConfig(qps=qps),
            qps=qps,
            max_retries=3,
            retry_backoff_base=0.8
        )

        try:
            await caller.run(start=0, limit=None)
        finally:
            await caller.close()
            logger.info(f"文件 {input_path.name} 处理结束，摘要：")
            print(json.dumps(caller.summary(), ensure_ascii=False, indent=2))
            
        # 可选：文件间稍微停顿
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())

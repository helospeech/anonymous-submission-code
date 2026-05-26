#!/bin/bash
# 顺序评测多个模型脚本
# 使用 tau2 评测 edu domain，user-llm 固定为 Qwen3.5-397B-A17B

set -u

# 待评测的 agent 模型列表
MODELS=(
  "GPT-4o-0806"
  "Doubao-Seed-2.0-pro"
  "GPT-4.1"
  "Qwen3.5-397B-A17B"
  "Kimi-K2.5"
  "Qwen3-235B-A22B"
  "gpt-5"
  "DeepSeek-V3.2"
  "GPT-5.4"
  "Gemini-3.1-Pro-Preview"
  "Claude-Opus-4.6"
  "GLM-5.1"
  "Claude-Sonnet-4.6"
  "MiniMax-M2.7"
)

# 日志保存目录
LOG_DIR="./eval_logs"
mkdir -p "$LOG_DIR"

# 公共参数
USER_LLM="Qwen3.5-397B-A17B"
DOMAIN="edu"
NUM_TRIALS=1
MAX_CONCURRENCY=3

TOTAL=${#MODELS[@]}
IDX=0

for MODEL in "${MODELS[@]}"; do
  IDX=$((IDX + 1))
  TS=$(date +"%Y%m%d_%H%M%S")
  # 把模型名里的 / 替换成 _ 防止路径问题
  SAFE_NAME=$(echo "$MODEL" | tr '/' '_')
  LOG_FILE="${LOG_DIR}/${SAFE_NAME}_${TS}.log"

  echo "==========================================================" | tee -a "$LOG_FILE"
  echo "[$IDX/$TOTAL] 开始评测模型: $MODEL" | tee -a "$LOG_FILE"
  echo "开始时间: $(date)" | tee -a "$LOG_FILE"
  echo "日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
  echo "==========================================================" | tee -a "$LOG_FILE"

  tau2 run \
    --domain "$DOMAIN" \
    --agent-llm "$MODEL" \
    --user-llm "$USER_LLM" \
    --inject-passage \
    --num-trials "$NUM_TRIALS" \
    --max-concurrency "$MAX_CONCURRENCY" \
    2>&1 | tee -a "$LOG_FILE"

  STATUS=${PIPESTATUS[0]}
  echo "----------------------------------------------------------" | tee -a "$LOG_FILE"
  echo "结束时间: $(date)" | tee -a "$LOG_FILE"
  echo "退出状态: $STATUS" | tee -a "$LOG_FILE"
  echo "" | tee -a "$LOG_FILE"
done

echo "全部评测完成，日志保存在: $LOG_DIR"
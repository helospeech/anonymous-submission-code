#!/bin/bash
# 统计 data/simulations/ 下各模型的分数 + token 数
# 评分: 调用 tau2 evaluate-trajs (框架自带)
# token: 直接读 JSON 中 messages[*].usage 字段
# 学段分数: 调用 grade_score.py 按小学/初中/高中分别统计
#
# 用法:
#   bash score_summary.sh                          # 默认目录，并行数=CPU核数
#   bash score_summary.sh /path/to/simulations     # 指定目录
#   bash score_summary.sh /path/to/simulations 8   # 指定并行数

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SIM_DIR="${1:-$SCRIPT_DIR/data/simulations}"
PARALLEL="${2:-$(nproc 2>/dev/null || echo 4)}"

if [ ! -d "$SIM_DIR" ]; then
    echo "目录不存在: $SIM_DIR"
    exit 1
fi

# 关闭 Rich 颜色，方便 grep
export NO_COLOR=1
export TERM=dumb
export FORCE_COLOR=0

# 按模型名分组，取每个模型的最新文件 (文件名前缀是时间戳)
declare -A MODEL_FILE
for f in $(find "$SIM_DIR" -maxdepth 1 -name "*.json" | sort -r); do
    fname=$(basename "$f")
    agent_model=$(echo "$fname" | sed -n 's/.*_edu_llm_agent_\(.*\)_user_simulator_.*/\1/p')
    [ -z "$agent_model" ] && continue
    if [ -z "${MODEL_FILE[$agent_model]}" ]; then
        MODEL_FILE[$agent_model]="$f"
    fi
done

if [ ${#MODEL_FILE[@]} -eq 0 ]; then
    echo "没有找到有效的 simulation JSON 文件"
    exit 1
fi

TMPDIR=$(mktemp -d /tmp/tau2_scores_XXXXXX)
echo "找到 ${#MODEL_FILE[@]} 个模型，并行评分中 (并行数: $PARALLEL) ..."
echo ""

# strip ANSI 颜色码的 sed 模式
ANSI_STRIP='s/\x1b\[[0-9;?]*[a-zA-Z]//g'

eval_one() {
    local agent_model="$1"
    local f="$2"
    local outfile="$3"
    local script_dir="$4"
    local fname
    fname=$(basename "$f")

    # 调用框架评分函数，去掉 ANSI 颜色码
    output=$(cd "$script_dir" && tau2 evaluate-trajs "$f" 2>&1 | sed "$ANSI_STRIP")

    avg_reward=$(echo "$output" | grep -oP 'Average Reward[:\s]*\K[0-9.]+' | head -1)
    pass1=$(echo "$output" | grep -oP 'k=1[:\s]*\K[0-9.]+' | head -1)
    avg_cost=$(echo "$output" | grep -oP 'Average Cost per Conversation[:\s\$]*\K[0-9.]+' | head -1)

    # 提取学段分数 (小学/初中/高中) - 格式: 小学avg|小学pass1|初中avg|初中pass1|高中avg|高中pass1
    grade_scores=$(python3 "$script_dir/grade_score.py" "$f" "$script_dir/task_grade_mapping.json" 2>/dev/null)
    primary_avg=$(echo "$grade_scores" | cut -d'|' -f1)
    primary_pass=$(echo "$grade_scores" | cut -d'|' -f2)
    junior_avg=$(echo "$grade_scores" | cut -d'|' -f3)
    junior_pass=$(echo "$grade_scores" | cut -d'|' -f4)
    senior_avg=$(echo "$grade_scores" | cut -d'|' -f5)
    senior_pass=$(echo "$grade_scores" | cut -d'|' -f6)

    # 提取 token 数 (从 JSON 里 assistant 消息的 usage 字段累加)
    tokens=$(python3 -c "
import json, sys
with open('$f','r',encoding='utf-8') as fp:
    d = json.load(fp)
pt=ct=tt=0
def walk(x):
    global pt,ct,tt
    if isinstance(x,dict):
        u=x.get('usage')
        role=x.get('role') or x.get('requestor')
        if isinstance(u,dict) and isinstance(role,str) and role.lower()=='assistant':
            pt+=int(u.get('prompt_tokens') or 0)
            ct+=int(u.get('completion_tokens') or 0)
            tt+=int(u.get('total_tokens') or 0)
        for v in x.values(): walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(d)
if tt==0: tt=pt+ct
print(f'{pt}|{ct}|{tt}')
" 2>/dev/null)
    prompt_tok=$(echo "$tokens" | cut -d'|' -f1)
    compl_tok=$(echo "$tokens" | cut -d'|' -f2)
    total_tok=$(echo "$tokens" | cut -d'|' -f3)

    [ -z "$avg_reward" ] && avg_reward="N/A"
    [ -z "$pass1" ] && pass1="N/A"
    [ -z "$avg_cost" ] && avg_cost="N/A"
    [ -z "$primary_avg" ] && primary_avg="N/A"
    [ -z "$primary_pass" ] && primary_pass="N/A"
    [ -z "$junior_avg" ] && junior_avg="N/A"
    [ -z "$junior_pass" ] && junior_pass="N/A"
    [ -z "$senior_avg" ] && senior_avg="N/A"
    [ -z "$senior_pass" ] && senior_pass="N/A"
    [ -z "$prompt_tok" ] && prompt_tok=0
    [ -z "$compl_tok" ] && compl_tok=0
    [ -z "$total_tok" ] && total_tok=0

    echo "$agent_model|$avg_reward|$pass1|$primary_avg|$primary_pass|$junior_avg|$junior_pass|$senior_avg|$senior_pass|$avg_cost|$prompt_tok|$compl_tok|$total_tok|$fname" > "$outfile"
    echo "  ✓ $agent_model  avg_reward=$avg_reward  pass^1=$pass1  小学(avg=$primary_avg,pass@1=$primary_pass)  初中(avg=$junior_avg,pass@1=$junior_pass)  高中(avg=$senior_avg,pass@1=$senior_pass)"
}
export -f eval_one
export ANSI_STRIP

job_idx=0
for agent_model in $(echo "${!MODEL_FILE[@]}" | tr ' ' '\n' | sort); do
    f="${MODEL_FILE[$agent_model]}"
    eval_one "$agent_model" "$f" "$TMPDIR/$job_idx.txt" "$SCRIPT_DIR" &
    job_idx=$((job_idx + 1))
    while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do
        wait -n 2>/dev/null || sleep 0.2
    done
done
wait

TMPFILE="$TMPDIR/all.txt"
cat "$TMPDIR"/[0-9]*.txt > "$TMPFILE" 2>/dev/null

echo ""
echo "============================================================================= 模型分数汇总 (按 Avg Reward 降序) =============================================================================="
printf "%-28s %9s %7s | %8s %8s | %8s %8s | %8s %8s | %9s %10s %10s %12s   %s\n" "模型" "AvgRwd" "Pass^1" "小学Avg" "小学P@1" "初中Avg" "初中P@1" "高中Avg" "高中P@1" "Cost($)" "PromptTok" "ComplTok" "TotalTok" "文件"
echo "------------------------------------------------------------------------------------------------------------------------------------------------------------------------------"
sort -t'|' -k2 -rn "$TMPFILE" | while IFS='|' read -r model reward pass pavg ppass javg jpass savg spass cost pt ct tt file; do
    printf "%-28s %9s %7s | %8s %8s | %8s %8s | %8s %8s | %9s %10s %10s %12s   %s\n" "$model" "$reward" "$pass" "$pavg" "$ppass" "$javg" "$jpass" "$savg" "$spass" "$cost" "$pt" "$ct" "$tt" "$file"
done
echo "============================================================================================================================================================================================================"
echo ""
echo "共 $(wc -l < "$TMPFILE") 个模型"

rm -rf "$TMPDIR"
#!/bin/bash

# 1. Path definitions
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_ROOT="$BASE_DIR/tau2-bench-main"
PIPELINE_DIR="$SCRIPT_DIR"
DATA_OUTPUT_DIR="$PIPELINE_DIR/tau2_data"

# 2. Deploy data to Tau2 edu domain
echo "=== Deploying generated tasks.json and db.json to Tau2 environment ==="
TARGET_DIR="$TAU2_ROOT/data/tau2/domains/edu"
mkdir -p "$TARGET_DIR"

if [ -f "$DATA_OUTPUT_DIR/tasks.json" ]; then
    cp "$DATA_OUTPUT_DIR/tasks.json" "$TARGET_DIR/tasks.json"
    cp "$DATA_OUTPUT_DIR/db.json" "$TARGET_DIR/db.json"
    
    # Dynamically generate split_tasks.json
    echo "=== Generating split_tasks.json ==="
    python3 -c "
import json
with open('$TARGET_DIR/tasks.json', 'r', encoding='utf-8') as f:
    tasks = json.load(f)
ids = [t['id'] for t in tasks]
with open('$TARGET_DIR/split_tasks.json', 'w', encoding='utf-8') as f:
    json.dump({'base': ids}, f, ensure_ascii=False)
"
    echo "Done: $TARGET_DIR"
else
    echo "Error: Data files not found. Please run 2_generate_qa.py first."
    exit 1
fi

# 3. Set Tau2 environment variables
export PYTHONPATH="$TAU2_ROOT/src:$PYTHONPATH"
export TAU2_DATA_DIR="$TAU2_ROOT/data"

if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "Error: OPENROUTER_API_KEY is not set!"
    echo "Please run: export OPENROUTER_API_KEY='your_api_key'"
    exit 1
fi

# LiteLLM + OpenAI-compatible API
export TAU2_API_BASE="https://openrouter.ai/api/v1"
export TAU2_API_KEY="$OPENROUTER_API_KEY"

# 4. Run Tau2 simulation
echo "=== Starting Tau2 simulation (generate-edu-trajs mode) ==="

cd "$TAU2_ROOT"

python3 -m tau2.cli generate-edu-trajs \
    --domain edu \
    --agent llm_agent \
    --user user_simulator \
    --agent-llm "Gemini 3-Pro-Preview" \
    --user-llm "Gemini 3-Pro-Preview" \
    --max-steps 30 \
    --num-trials 4 \
    --max-concurrency 10 \
    --save-to "edu_simulation_$(date +%Y%m%d_%H%M%S)"

echo "=== Simulation complete ==="
echo "Trajectory files saved in: $TAU2_ROOT/data/simulations/"
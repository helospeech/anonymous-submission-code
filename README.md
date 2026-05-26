# EduAgent-Bench: Evaluating LLM Agents as Adaptive Teaching Assistants

This project extends the [τ²-bench](https://github.com/sierra-research/tau2-bench) framework by introducing the **edu** domain (education scenario), which evaluates LLM agents as adaptive teaching assistants in Chinese language education dialogues.

## Project Structure

```
submission/
├── origin-data/                # Raw textbook & teacher's guide data (elementary/middle/high school)
│   ├── 小学txt/                # Elementary school textbooks & teacher's guides (txt)
│   └── 初高中教材-教师用书-markdown/  # Middle & high school materials (markdown)
├── md_data_pipeline/           # Data synthesis pipeline (markdown-based)
│   ├── test_extract.py         # Textbook content extraction
│   ├── 2_generate_qa.py       # Generate QA & teaching tasks via LLM
│   ├── llm_client.py          # LLM API client utilities
│   ├── run_simulation.sh      # Run simulation script
│   ├── dataset_extracted.json # Extracted dataset
│   └── tau2_data/             # Output: db.json & tasks.json for tau2 framework
└── tau2-bench-main/            # Evaluation framework (extended from τ²-bench)
    ├── src/tau2/domains/edu/   # Edu domain implementation (our core contribution)
    ├── data/tau2/domains/edu/  # Edu domain data files
    ├── data_generation/        # Legacy data generation pipeline
    ├── scripts/run_eval.sh     # Batch evaluation script
    ├── grade_score.py          # Grade-level scoring
    ├── score_summary.sh        # Score aggregation
    └── ... (remaining code from the original τ²-bench framework)
```

## Our Contributions (relative to the original τ²-bench)

1. **New edu domain** (`src/tau2/domains/edu/`): Teaching environment, agent toolkits, student simulator toolkits, and data models
2. **Data synthesis pipeline** (`md_data_pipeline/`): Extract content from real textbooks and synthesize teaching tasks via LLMs
3. **Diverse student persona simulation**: Includes mischievous, introverted, and other student behavioral personas
4. **Grade-level evaluation** (`grade_score.py`): Computes pass@1 and avg_reward separately for elementary, middle, and high school
5. **User simulator extension** (`data/tau2/user_simulator/simulation_guidelines_tools_edu.md`): Student simulation guidelines designed specifically for educational scenarios

## Quick Start

```bash
cd tau2-bench-main
pip install -e .

# Run edu domain evaluation
tau2 run --domain edu --agent-llm gpt-4.1 --user-llm gpt-4.1 --num-trials 1

# View scores by grade level
python grade_score.py data/simulations/<result>.json

# Batch evaluation
bash scripts/run_eval.sh
```

## Additional Notes

- `tau2-bench-main/data/pridict_role.py` classifies student personas from evaluation trajectories
- `origin-data/stats_result.json` contains statistics of the raw data
- `md_data_pipeline/tau2_data/` contains the generated `db.json` and `tasks.json` that can be copied into `tau2-bench-main/data/tau2/domains/edu/`
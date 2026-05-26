# SocraticGym: Evaluating and Aligning LLMs for Socratic Pedagogy

  This repository contains the anonymized implementation for **SocraticGym**, an interactive environment for evaluating and aligning large language models (LLMs) for Socratic pedagogy.

  SocraticGym focuses on whether an LLM teacher can guide a simulated student toward understanding, rather than simply providing the correct answer. The environment tracks the student's hidden cognitive state through structured cognitive defects and verifies task success only when the student simulator marks these defects as resolved after receiving appropriate scaffolding.

  This repository is provided for double-blind review. Author, affiliation, and project-identifying information are intentionally omitted during the review period.

---

  ## Overview

  SocraticGym is an asymmetric interactive environment for pedagogical evaluation and alignment. It is designed around a teacher-student interaction:

  - The **teacher LLM** interacts with a student through natural language.
  - The **student simulator** maintains hidden cognitive defects and behavioral constraints.
  - The teacher does **not** have direct access to the student's hidden cognitive state.
  - A cognitive defect is marked as resolved only when the teacher provides valid step-by-step guidance.
  - Direct answer-giving or premature solution revelation is rejected by the simulator through an anti-spoon-feeding mechanism.

  In this repository, SocraticGym is instantiated for **K--12 Chinese curriculum text teaching**, covering primary, junior secondary, and senior secondary teaching tasks.

---

  ## Main Features

  - **Interactive Socratic teaching environment**
  - **Stateful student simulator**
  - **Anti-spoon-feeding mechanism**
  - **Objective state-based evaluation**
  - **K--12 curriculum text teaching benchmark**
  - **Support for supervised fine-tuning and reinforcement learning**

---

  ## Project Structure

  ```text
  submission/
  ├── md_data_pipeline/          # Data synthesis pipeline
  │   ├── test_extract.py        # Extract lesson-level content
  │   ├── 2_generate_qa.py       # Generate cognitive defects and teaching tasks
  │   ├── llm_client.py          # LLM API client utilities
  │   ├── run_simulation.sh      # Simulation or generation script
  │   ├── dataset_extracted.json # Intermediate extracted dataset, if included
  │   └── tau2_data/             # Generated db.json and tasks.json
  └── tau2-bench-main/           # Interactive evaluation framework
      ├── src/tau2/domains/edu/  # SocraticGym education-domain implementation
      ├── data/tau2/domains/edu/ # SocraticGym task data
      ├── data_generation/       # Data-generation utilities
      ├── scripts/run_eval.sh    # Batch evaluation script
      ├── grade_score.py         # Grade-level scoring
      ├── score_summary.sh       # Score summarization
      └── ...
  ```

---

  ## Relationship to the Base Framework

  SocraticGym builds on the public [`τ²-bench`](https://github.com/sierra-research/tau2-bench) framework and extends it from operational task completion to epistemic pedagogical interaction.

  Compared with the original framework, this repository adds:

  1. **Education-domain environment**
  2. **Latent cognitive-state modeling**
  3. **Anti-spoon-feeding constraints**
  4. **Data synthesis pipeline**
  5. **Grade-level evaluation**
  6. **Pedagogical alignment support**

---

  ## Environment Design

  SocraticGym formalizes teaching as an asymmetric partially observable interaction.

  The **teacher LLM** interacts with a cognitively restricted **student simulator**. The simulator maintains hidden cognitive defects and decides whether the teacher's guidance is pedagogically valid.

  A defect is marked as resolved only when the teacher provides appropriate scaffolding. If the teacher directly reveals the answer without sufficient guidance, the simulator does not mark the defect as resolved.

  The cognitive defects are organized into three levels:

  - **D1: Surface / factual defects**  
    Misunderstanding vocabulary, literal details, or explicit information.

  - **D2: Relational / reasoning defects**  
    Failing to connect events, causes, structures, or evidence.

  - **D3: Deep / affective defects**  
    Failing to grasp metaphor, theme, authorial intention, or emotional resonance.

---

  ## Evaluation Metrics

  SocraticGym uses objective state-based metrics.

  - **S_succ**: end-to-end success rate.  
    A task succeeds only if all predefined cognitive defects are resolved within the interaction budget.

  - **S_proc**: process score.  
    This measures the fraction of cognitive defects resolved by the end of the interaction.

---

  ## Installation

  The main environment code is under `tau2-bench-main/`.

  ```bash
  cd tau2-bench-main
  pip install -e .
  ```

  Install additional dependencies if needed:

  ```bash
  pip install -r requirements.txt
  ```

---

  ## Data Preparation

  Raw textbook passages and teacher-reference-book contents are **not included** in this anonymous repository due to copyright and redistribution constraints.

  Please obtain the required curriculum materials through authorized channels and place them under `origin-data/`.

  A recommended local structure is:

  ```text
  origin-data/
  ├── primary/
  │   ├── textbooks/
  │   └── teacher_references/
  ├── junior_secondary/
  │   ├── textbooks/
  │   └── teacher_references/
  └── senior_secondary/
      ├── textbooks/
      └── teacher_references/
  ```

---

  ## Generating Teaching Tasks

  From the repository root:

  ```bash
  cd md_data_pipeline
  ```

  Run extraction:

  ```bash
  python test_extract.py
  ```

  Generate cognitive defects and teaching tasks:

  ```bash
  python 2_generate_qa.py
  ```

  The generated files should include:

  ```text
  db.json
  tasks.json
  ```

  Copy them into the environment domain directory:

  ```bash
  cp tau2_data/db.json ../tau2-bench-main/data/tau2/domains/edu/
  cp tau2_data/tasks.json ../tau2-bench-main/data/tau2/domains/edu/
  ```

---

  ## Running Evaluation

  Enter the main environment directory:

  ```bash
  cd tau2-bench-main
  ```

  Run an example evaluation:

  ```bash
  tau2 run \
    --domain edu \
    --agent-llm gpt-4.1 \
    --user-llm qwen3.5-397b-a17b \
    --num-trials 1
  ```

  Run evaluation with multiple trials:

  ```bash
  tau2 run \
    --domain edu \
    --agent-llm gpt-4.1 \
    --user-llm qwen3.5-397b-a17b \
    --num-trials 4
  ```

  Model names may need to be adapted to your local backend configuration.

---

  ## Reproducing Main Experiments

  A typical reproduction workflow is:

  ```bash
  cd tau2-bench-main
  pip install -e .
  ```

  Set API credentials:

  ```bash
  export OPENAI_API_KEY=<your_api_key>
  ```

  Prepare task files:

  ```bash
  cp ../md_data_pipeline/tau2_data/db.json data/tau2/domains/edu/
  cp ../md_data_pipeline/tau2_data/tasks.json data/tau2/domains/edu/
  ```

  Run evaluation:

  ```bash
  tau2 run \
    --domain edu \
    --agent-llm gpt-4.1 \
    --user-llm qwen3.5-397b-a17b \
    --num-trials 4
  ```

  Compute scores:

  ```bash
  python grade_score.py data/simulations/<result_file>.json
  ```

---

  ## Notes on Copyrighted Materials

  This project uses official curriculum materials and teacher-reference books as source materials for benchmark construction.

  These materials are copyrighted by their respective publishers. The original textbook passages and teacher-reference-book contents are **not redistributed** in this repository.

  This repository provides environment code, data-processing scripts, task metadata format, derived annotations where legally permitted, and instructions for authorized data preparation.

  Users are responsible for obtaining any required source materials through authorized channels.

---

  ## Notes for Anonymous Review

  This repository is prepared for double-blind review.

  During the review period:

  - author names are omitted
  - affiliations are omitted
  - personal or institutional links are omitted
  - citation metadata for this repository is omitted
  - raw copyrighted educational materials are not redistributed
  - API keys, private endpoints, and local configuration files are excluded

  Project-identifying information will be restored after the review period where appropriate.

---

  ## Citation

  Citation information is omitted during double-blind review and will be added after the review period.

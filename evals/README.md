# Eval Suites

Two eval suites exist for different knowledge bases.

## Loomo Suite (active)

- **Runner:** `eval_loomo.py`
- **Questions:** `eval_suite_loomo.json` (58 questions)
- **KB:** Customer-facing Loomo policy docs (`kb/`)
- **Current score:** 54/58 (93.1%)

```bash
# From project root:
python3 evals/eval_loomo.py

# Or via run.sh:
bash evals/run.sh loomo
```

## Legacy Suite

- **Runner:** `run_evals.py`
- **Questions:** `questions.json` (79 questions)
- **KB:** Internal HR/ops KB (not included in repo)
- **Judge:** `llm_judge.py` (optional LLM-based scoring)

```bash
# From project root:
python3 evals/run_evals.py --skip-judge

# Or via run.sh:
bash evals/run.sh legacy
```

## Prerequisites

Dot must be running before eval:

```bash
cd /path/to/project
source .venv/bin/activate
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Results are written to `evals/results/` (gitignored).

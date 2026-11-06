# MP4: Agentic C-to-Rust translation (Team 15)

Assigned projects (Group 15): **project_1 = `bigint`**, **project_2 = `razz_simulation`**.

> Draft: sections marked TODO must be filled in after the real runs.

## Pipeline overview
Four cooperating agents (same model, different prompts, tools and write permissions):

| Agent | Role | May write |
|---|---|---|
| Orchestrator | reads harness feedback, picks the next agent (JSON, validated, deterministic fallback) | nothing |
| Reader | reads C + Rust interface + tests, writes the behavioural spec | `notes/spec*.md` |
| Writer | writes/repairs the Rust translation | `src/**` |
| Tester | writes extra tests (C binary used as an oracle for expected values), analyses failures | `tests/extra_*.rs`, `notes/**` |

A deterministic **harness** (`src/harness.py`) runs `cargo build/test/clippy` with the pinned toolchain and the
unsafe-metrics tool, compresses the output and returns it to the agents.

Phase A: compile and pass the CRUST tests. Phase B: reduce unsafe and Clippy findings; any round that breaks
tests or fails to improve the score is reverted.

**Stopping conditions:** success (all metrics zero), Phase B round limit, max iterations, token budget, or the
same failure repeated `stall_rounds` times (after one Reader escalation).

## Setup (TODO: verify versions after first run)
- Framework: custom Python 3 controller (stdlib only, no pip dependencies), `src/`.
- Model: Gemma 4 via OpenRouter (exact model id in `configs/model.json`), temperature 0.2, max_tokens 8192.
- Toolchain: `rustup toolchain install nightly-2025-05-13 -c clippy,rustfmt`
- OS/runtime: macOS (Darwin 24.6), Python 3.15.
- Tools available to agents: read_file, list_dir, grep, write_file (permissioned), run_cargo
  (check/build/test/clippy/unsafe), run_c_oracle (tester only).
- API limits that affected the run: TODO.

## Run
```bash
export OPENROUTER_API_KEY=...        # never commit
./src/run.sh 1 subjects/project_1/bigint subjects/project_1/rust_template
./src/run.sh 2 subjects/project_2/razz_simulation subjects/project_2/rust_template
python3 src/smoke_test.py <scratch-dir>   # offline self-test, no API key needed
```

## Layout
`src/` pipeline code, `configs/` model/pipeline settings and prompts, `subjects/` original C,
`translations/` final Rust, `trajectories/` logs (`trajectory.jsonl`, `iterations.json`, `final_status.json`, notes).

## Manual interventions
None so far (TODO: document any infrastructure-only changes).

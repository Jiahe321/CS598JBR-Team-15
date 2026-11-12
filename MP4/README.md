# MP4: Agentic C-to-Rust Translation

## Environment

- Agent framework: the repository's custom Python orchestration controller; it uses Reader, Writer, Tester, and Orchestrator roles. No external agent framework package is required.
- Model/provider: DeepSeek API, `deepseek-flash`, using `https://api.deepseek.com`. DeepSeek currently documents this model alias as V4.1 Flash ([model details](https://api-docs.deepseek.com/quick_start/pricing/)).
- Inference settings sent by the controller: temperature `0.2`, top-p `0.95`, maximum output `8192` tokens, thinking disabled, 120-second request timeout, and up to 2 attempts. The provider may ignore some sampling parameters in non-thinking mode.
- Local runtime: Windows PowerShell, Python 3.13.15, Rust `nightly-2025-05-13` (rustc 1.89.0-nightly), and MinGW GCC 16.2.0. Python dependencies are all from the standard library.
- Tools available to agents: scoped file read/search/write actions, Cargo check/build/test/Clippy, and a temporary GCC C oracle. Each outer iteration now runs the local built-in unsafe-source scan and returns its counts to the agent. The separate `newmetrics/` analyzer in this repository is not wired into the controller.
- Per-project run limits: 5 outer iterations, 20 provider HTTP requests (including retries), 500,000 total tokens, 3 repeated-stall rounds, and 4 Phase B rounds. The account's remaining API quota is provider-specific and has not been checked.
- Current run state: Project 1 has a partial translation and trajectory from an earlier run; Project 2 has its C source and Rust template, but no generated translation or trajectory yet. Treat neither project as complete until its new `final_status.json` is reviewed.

The model and pipeline settings are in `configs/model.json` and `configs/pipeline.json`; prompts are in `configs/prompts/`. The controller reads `MP4/.env` automatically and does not overwrite variables already set in the shell. Copy `.env.example` to `.env`, then set `DEEPSEEK_API_KEY`. Keep `.env` private; it is ignored by Git.

## Dependencies

Python requires no package installation. Install the pinned Rust toolchain and Clippy:

```powershell
rustup toolchain install nightly-2025-05-13 -c clippy,rustfmt
```

Install GCC or Clang if the C-oracle tests are to be used. On Windows, the one-command runner selects `x86_64-pc-windows-gnu` when MSVC linker tools are unavailable; install that Rust target and MinGW if needed:

```powershell
rustup target add x86_64-pc-windows-gnu --toolchain nightly-2025-05-13
```

## Run both assigned projects

From the repository root, run:

```powershell
.\MP4\src\run_all.ps1
```

The script checks the required tools and input directories, runs Project 1 and then Project 2, and prints each final status. It resumes a project when a generated `translations/project_<N>/src/` already exists; otherwise it starts from the supplied template. Use `-MaxIterations N` or `-MaxLlmRequests N` to override the per-project limits. Use `-Fresh` only when you want to replace both projects' generated translations and clear their trajectories before running.

To run one project directly:

```powershell
python MP4/src/pipeline.py --project 1 --c-dir MP4/subjects/project_1/bigint --rust-template MP4/subjects/project_1/rust_template
python MP4/src/pipeline.py --project 2 --c-dir MP4/subjects/project_2/razz_simulation --rust-template MP4/subjects/project_2/rust_template
```

If using the direct command on Windows without MSVC tools, add `--cargo-target x86_64-pc-windows-gnu`. On macOS/Linux, the pipeline uses the host Rust target. `src/run.sh` is the macOS/Linux single-project wrapper.

## Pipeline and stopping conditions

The Reader analyzes the C project, Rust interface, and tests and writes behavioral specifications. The Writer implements and repairs Rust. The Tester reviews failures, can add extra Rust tests, and can query a temporary C oracle. The Orchestrator selects the next role using the latest Cargo feedback.

Phase A stops when interface checks and tests pass, the configured iteration/token/request budget is reached, or failures stall. After each outer iteration, the controller runs build/tests and the local unsafe-source scan; Phase B also runs Clippy and tries up to 4 metric-reduction rounds while keeping tests passing. Changes that break tests or fail to improve the configured score are reverted. The model receives build, test, safety-estimate, and (in Phase B) Clippy feedback after each evaluation.

The C source is read-only to the agents. Rust output is compiled independently and does not link to the C implementation. The pipeline preserves the supplied interface and test files.

## Outputs and reproducibility

Each run writes:

- `translations/project_<N>/`: the generated Rust crate.
- `trajectories/project_<N>/trajectory.jsonl`: agent actions, tool results, and evaluation events.
- `trajectories/project_<N>/iterations.json`: iteration history.
- `trajectories/project_<N>/final_status.json`: final status and evaluation summary.
- `trajectories/project_<N>/notes/` and `snapshots/`: behavioral specifications and source snapshots.

Review trajectories for credentials before committing. The logger redacts configured API key values, but the final repository should still be checked before submission. Update the environment and results sections after both runs finish; do not present partial artifacts as completed experiments.

The course's required evaluation toolchain is `nightly-2025-05-13`. Run `cargo +nightly-2025-05-13 build`, `cargo +nightly-2025-05-13 test`, and the specified Clippy categories on each final crate before submission. The built-in unsafe scan is an estimate and must not be reported as output from the separate `newmetrics/` analyzer or the course-provided unsafe-metrics analyzer.

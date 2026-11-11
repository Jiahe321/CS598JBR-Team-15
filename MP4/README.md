# MP4: Agentic C-to-Rust Translation

## Environment

- Agent framework and version: TODO
- Model(s) and provider/runtime: TODO
- Inference settings (temperature, token limits, etc.): TODO 
- OS/runtime: TODO
- Tools available to the agent: Cargo, Rust compiler, Clippy, unsafe-metrics tool (update as used)
- API or usage limits: TODO

## Setup

The controller uses Python's standard library and does not require Python packages. Install Rust with `rustup`, then install the toolchain and Clippy component configured for this project:

```bash
rustup toolchain install nightly-2025-05-13 -c clippy,rustfmt
```

Set `OPENROUTER_API_KEY` in the shell used to launch the controller. Do not commit the key or put it in this README. The model endpoint and inference settings are configured in `configs/model.json`; pipeline limits and tool settings are in `configs/pipeline.json`.

## Run

Run commands from the repository root. On macOS/Linux, `src/run.sh` changes into `MP4/` before running the controller, so pass input directories relative to `MP4/`:

```bash
export OPENROUTER_API_KEY="<your key>"
./MP4/src/run.sh 1 subjects/project_1/bigint subjects/project_1/rust_template
./MP4/src/run.sh 2 subjects/project_2/razz_simulation subjects/project_2/rust_template
```

The controller can also be invoked directly, including on Windows:

```powershell
$env:OPENROUTER_API_KEY = "<your key>"
python MP4/src/pipeline.py --project 1 --c-dir MP4/subjects/project_1/bigint --rust-template MP4/subjects/project_1/rust_template
python MP4/src/pipeline.py --project 2 --c-dir MP4/subjects/project_2/razz_simulation --rust-template MP4/subjects/project_2/rust_template
```

Add `--clean` to start from the supplied Rust template and clear that project's trajectory output. Add `--resume` to continue an existing run. These options cannot be used together. `--max-iterations N` overrides the configured iteration limit. On Windows, if the MSVC linker is unavailable, install the GNU target and pass `--cargo-target x86_64-pc-windows-gnu`.

## Pipeline

The controller in `src/pipeline.py` coordinates three specialist agents and an orchestrator. The Reader analyzes the C sources, Rust interfaces, and tests and writes behavioral specifications. The Writer implements or repairs Rust code. The Tester analyzes failures, can add extra Rust tests, and can use a temporary C executable as an oracle. The Orchestrator selects the next action from the latest harness report.

For each project, the pipeline prepares a Rust translation from the supplied template, runs the agents and Cargo harness in an iterative feedback loop, and checks interface signatures and CRUST tests. Once Phase A passes, Phase B attempts to reduce Clippy findings and unsafe-code metrics while preserving passing tests; a change that breaks tests or does not improve the score is reverted. Runs stop on success, configured iteration or token limits, the Phase B limit, or repeated stalled failures.

The C project is used as read-only input. The Rust translation is independent and does not link to or call the C project. Agent file permissions are role-limited by `src/tools.py`.

## Outputs

Generated artifacts are stored under `translations/project_<N>/` and `trajectories/project_<N>/`:

- `translations/project_<N>/`: the Rust translation produced by the run.
- `trajectories/project_<N>/trajectory.jsonl`: chronological agent, tool, and harness events.
- `trajectories/project_<N>/iterations.json`: iteration history and run details.
- `trajectories/project_<N>/final_status.json`: final status, phase, and evaluation summary.
- `trajectories/project_<N>/notes/`: behavioral specifications and analysis notes.
- `trajectories/project_<N>/snapshots/`: source snapshots used during the run.

Retain these artifacts with the submission. A project should only be reported as completed after its run has generated a non-empty trajectory, an iterations file, and a final status.

## Evaluation

Phase A evaluates whether the Rust crate builds, the required public interface signatures match, and the CRUST tests pass. Phase B reports Clippy findings by category and unsafe-code metrics. The pipeline's combined score sums the Clippy counts and the configured unsafe metrics; Phase B retains improvements only when tests continue to pass.

The official unsafe-metrics tool is not configured by default (`unsafe_metrics_cmd` is `null` in `configs/pipeline.json`). In that case the harness reports its built-in source scan as an estimate. Identify the metric source when reporting results, and do not describe the estimate as the course-provided analyzer's result.

No experiments have been run for this README revision. Populate the Environment section and report project results after running the workflow; do not infer experimental results from the checked-in trajectory files.

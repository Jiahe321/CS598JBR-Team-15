# MP4: Agentic C-to-Rust Translation

## Environment

- Agent framework: the repository's custom Python orchestration controller; it uses Reader, Writer, Tester, and Orchestrator roles. No external agent framework package is required.
- Model/provider: DeepSeek API, `deepseek-flash`, using `https://api.deepseek.com`. DeepSeek currently documents this model alias as V4.1 Flash ([model details](https://api-docs.deepseek.com/quick_start/pricing/)).
- Inference settings sent by the controller: temperature `0.2`, top-p `0.95`, maximum output `8192` tokens, thinking disabled, 120-second request timeout, and up to 2 attempts. The provider may ignore some sampling parameters in non-thinking mode.
- Local execution uses Windows PowerShell or Git Bash and Rust `nightly-2025-05-13`. Python 3.11 or newer is required for the standard-library `tomllib` module. Python dependencies are all from the standard library; a C compiler is needed for the C oracle.
- Tools available to agents: scoped file read/search/write actions, Cargo check/build/test/Clippy, and a temporary GCC C oracle. Each outer iteration now runs the local built-in unsafe-source scan and returns its counts to the agent. The separate `newmetrics/` analyzer in this repository is not wired into the controller.
- Default per-project run limits: 10 outer iterations, 80 provider HTTP requests (including retries), 750,000 cumulative tokens, 3 repeated-stall rounds, and 4 Phase B rounds. CLI options can override the iteration and request limits.
- Historical checkpoint: earlier runs stopped at the former 500,000-token cumulative limit. The current controller raises that cap to 750,000; prior run results are recorded below for context.

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

The script checks the required tools and input directories, runs Project 1 and then Project 2, and prints each final status. It resumes a project when a generated `translations/project_<N>/src/` already exists; otherwise it starts from the supplied template. Use `-MaxIterations N` or `-MaxLlmRequests N` to override the per-project limits. `-Fresh` archives and regenerates both projects; use the single-project command below to regenerate Project 2 while preserving Project 1.

To run one project directly:

```powershell
python MP4/src/pipeline.py --project 1 --c-dir MP4/subjects/project_1/bigint --rust-template MP4/subjects/project_1/rust_template
python MP4/src/pipeline.py --project 2 --c-dir MP4/subjects/project_2/razz_simulation --rust-template MP4/subjects/project_2/rust_template
```

If using the direct command on Windows without MSVC tools, add `--cargo-target x86_64-pc-windows-gnu`. On macOS/Linux, the pipeline uses the host Rust target. `src/run.sh` is the macOS/Linux single-project wrapper.

### Regenerate Project 2 in the submission directories

From the repository root in Git Bash:

```bash
MP4/.venv/Scripts/python.exe -u MP4/src/pipeline.py \
  --project 2 \
  --c-dir MP4/subjects/project_2/razz_simulation \
  --rust-template MP4/subjects/project_2/rust_template \
  --clean \
  --max-iterations 6 \
  --max-llm-requests 60
```

`--clean` first copies the existing Project 2 translation and trajectory directories to
`MP4/backups/project_2_<UTC timestamp>/`, excluding build caches. It then rebuilds only Project 2
from the supplied template. New source goes to `MP4/translations/project_2/`; new results go to
`MP4/trajectories/project_2/`. The backup path is printed and included in the new `setup` event.
Local backups are ignored by Git. Use `--continue` on subsequent repair runs; it cannot be combined
with `--clean`. Deleting `card.rs` alone does not reset the other modules, notes, or review state.

## Pipeline and stopping conditions

The Reader analyzes the C project, Rust interface, and tests and writes behavioral specifications. The Writer implements and repairs Rust. The Tester reviews failures, can add extra Rust tests, and can query a temporary C oracle. The controller routes compiler errors directly to Writer and behavioral failures to Tester followed by Writer.

Phase A proceeds to Phase B when required interface checks and provided and extra tests pass. A run also stops when the configured iteration/token/request budget is reached, failures stall, or an agent reports an evidenced `spec_gap` or missing evidence. Currently, `spec_gap` stops the entire run; continuing repairs to independent issues after that report is not implemented. After each outer iteration, the controller runs build/tests and the local unsafe-source scan; Phase B also runs Clippy and tries up to 4 metric-reduction rounds while keeping tests passing. Changes that break tests or fail to improve the configured score are reverted. The model receives build, test, safety-estimate, and (in Phase B) Clippy feedback after each evaluation.

The C source is read-only to the agents. Rust output is compiled independently and does not link to the C implementation. The pipeline preserves the supplied interface and test files.

### Agent limits

Initial Reader and Writer tasks receive a bounded source packet containing complete current Rust
files, C sources/headers/tests, and existing specifications. The packet is capped at 120,000
characters; omitted paths are listed explicitly. Supplied files consume no tool-read actions. Once
Writer has replaced the initial placeholder modules, the large C/test/spec packet is replaced by current
Rust snapshots capped at 40,000 characters and an available-path catalog. Compiler repairs receive
complete compiler-reported Rust files within a 48,000-character packet. These changes reduce repeated
input tokens during compilation and repair. Every new invocation refreshes evidence from disk.
A successful complete model write is recognized as known source at its new digest, so the same agent
can fix that version without rereading it merely to satisfy the full-file write guard.

| Role and mode | Maximum replies per invocation | Additional source-read actions |
| --- | --- | --- |
| Reader, initial specification | 6 | 32 |
| Reader, focused refresh | 4 | 8 |
| Writer, initial generation | 18 | 40 |
| Writer, focused repair | 12 | 16 |
| Tester, failure analysis | Up to 6 provider requests, including retries | 16 |
| Tester, extra-test generation | 10 | 24 |

Each invocation also allows 6 directory/search actions and at most 8 actions per reply. Initial Reader
analysis is capped at 160,000 tokens; focused analysis defaults to 60,000. Analysis invocations have
provider-request allowances and reserve requests and tokens for Writer when possible. The global
750,000-token cap, configured request cap (80 by default, 60 in the regeneration command above), and
iteration limits all apply.
An `EVIDENCE_REQUIRED:` marker anywhere in an agent's completion summary prevents it from being
accepted as a completed specification or repair. `stop_details` in the final status records the agent
and evidence when a run stops for missing evidence or a contract gap.

Token usage counts cumulative provider-reported input and output, including cached input tokens.
The configured 8,192-token maximum is a per-response completion limit. Before each request the
controller estimates prompt size with headroom and reserves the maximum completion against the
cumulative cap; this estimate can stop a run before the exact cap. `llm_request` records the
estimated prompt size and completion allowance.

## Checkpoint results (2026-11-12)

This is a progress checkpoint. The supplied benchmark tests remain unchanged.

| Project | Build | Provided Cargo tests | Saved pipeline status |
| --- | --- | --- | --- |
| Project 1 | Pass | 16/16 executions passed | `token_budget` during Phase B quality work |
| Project 2, latest fresh generation | Fail | Not executed: build failed | `token_budget` before outer repair iterations |

Project 1's Cargo layout executes 8 distinct test functions through both binary and integration targets,
giving 16 executions. Its passing visible tests do not certify hidden tests or completion of quality work.
The saved status is from the earlier pipeline run; a later direct local test run also passed 16/16.

Before fresh regeneration, Project 2 had an archived repair checkpoint that compiled but passed 0/1
provided tests and stopped with `spec_gap`. That run made 19 requests and used 370,714 tokens. Its diagnostic run recorded
104,223 passed and 56 failed assertion executions at three failing assertion sites. These diagnostic
counts do not replace the official Cargo result of 0/1 and are not a functional-correctness score.
Those measurements belong to the archived version under `backups/`, not the freshly generated code.

The latest fresh run made 12 requests and used 545,375 tokens (530,988 input and 14,387 output).
Reader completed in one request; Writer generated both modules in its first two replies. Orphan DSML
closing tags were accidentally included in those files, causing compilation to fail. Repeated full-file
reads and the retained initial source packet consumed the remaining budget. The last request started
at 499,454 cumulative tokens and consumed another 45,921; the previous budget check only examined
usage already spent. The controller has since been updated to remove orphan DSML parameter endings,
recognize its own complete writes, compact generation context, and check the estimated next request.
These fixes have not yet been validated by another model run. The generated source is retained for
repair with `--continue`; the latest failure record remains in `trajectories/project_2/final_status.json`.

Known test-contract differences:

- The upstream [CRUST-bench issue #42](https://github.com/anirudhkhatry/CRUST-bench/issues/42)
  reports that the C `razz_simulation` tests reset the RNG with `srand48(3)`, while the Rust tests
  omit those resets but expect the same random outputs. The repository owner acknowledged the
  discrepancy. The issue was still open when checked on 2026-11-12.
- A separate local comparison found that `subjects/project_2/razz_simulation/card_test.c:317`
  removes `SPADE_ACE` after three insertions. The supplied Rust test instead performs a fourth
  insertion at `subjects/project_2/rust_template/src/bin/test.rs:214`, then still expects two cards
  at line 217. This difference is also present in the local original dataset archive; it has not
  been confirmed by an upstream maintainer in issue #42.

The earlier Project 2 translation also had implementation work remaining: its generated deck constructor reset the RNG
on every construction, which repeats draws across newly created decks; interface warnings and an
unimplemented removal helper remain. An upstream test discrepancy does not explain away these
implementation problems. Those findings concern the archived translation; the fresh implementation
requires its own build and behavioral evaluation. Agent-written specifications and analyses are retained
as trajectory artifacts; their hypotheses require checking against source and are not validated facts.

Project 1's five external safety-analysis files are already tracked. Project 2's local `summary.json`,
`newmetrics.log`, `unsafe_spans.txt`, `decls.txt`, and `derefs.txt` predate its latest Rust edits and
should be regenerated before being submitted as measurements of the current translation. The
`unsafe` values in pipeline reports are the separate built-in estimates.

## Outputs and reproducibility

To continue repairing an existing translation, add `--continue`. To check an existing passing translation
and stop before extra-test generation or quality edits, combine `--continue --stop-after-tests`.
For example, to preserve project 1 while checking its current visible tests:

```bash
MP4/.venv/Scripts/python.exe -u MP4/src/pipeline.py --project 1 --c-dir MP4/subjects/project_1/bigint --rust-template MP4/subjects/project_1/rust_template --continue --stop-after-tests
```

The stop option exits as soon as the provided and extra tests pass. This does not certify hidden tests.
Use `--out-root PATH` for a separate experiment directory when trying a fresh translation; its outputs
will be placed under `PATH/translations/` and `PATH/trajectories/`.

Each run writes:

- `translations/project_<N>/`: the generated Rust crate.
- `trajectories/project_<N>/trajectory.jsonl`: agent actions, tool results, and evaluation events appended
  across runs, including with `--continue`. Each run begins with a `setup` event containing a UTC
  `started_at` timestamp; event `t` values are elapsed seconds within that run. `--clean` starts a new
  trajectory after archiving this project's previous source and results under `backups/`.
- `trajectories/project_<N>/iterations.json`: iteration history.
- `trajectories/project_<N>/final_status.json`: final status and evaluation summary for the latest run;
  this JSON file is still overwritten on completion.
- `trajectories/project_<N>/notes/` and `snapshots/`: behavioral specifications and source snapshots.

Review trajectories for credentials before committing. The logger redacts configured API key values, but the final repository should still be checked before submission. Update the environment and results sections after both runs finish; do not present partial artifacts as completed experiments.

The course's required evaluation toolchain is `nightly-2025-05-13`. Run `cargo +nightly-2025-05-13 build`, `cargo +nightly-2025-05-13 test`, and the specified Clippy categories on each final crate before submission. The built-in unsafe scan is an estimate and must not be reported as output from the separate `newmetrics/` analyzer or the course-provided unsafe-metrics analyzer.

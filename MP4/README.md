# MP4: Agentic C-to-Rust Translation

This project translates the team's assigned CRUST-Bench projects, **bigint** and
**razz_simulation**, using a reusable Python controller and model-driven repair.
The saved experiments use Rust `nightly-2025-05-13`. Project 1 passes the provided
tests; Project 2 compiles but retains a failing benchmark test and documented
behavioral limitations.

## Environment and versions

| Component | Experiment setting |
| --- | --- |
| Agent framework | Custom Python controller in [src/](src/); no third-party agent framework package |
| Source checkpoints | Project 1: Git `3d05f39`; Project 2: Git `7a12588` |
| Agent roles | Reader, Writer, and Tester share the same model; the controller routes tasks and feedback. An Orchestrator helper is also included in the source. |
| Model and provider | DeepSeek API, configured model alias `deepseek-flash`, endpoint `https://api.deepseek.com` |
| OS and shells | Windows x64, OS build `10.0.26200.0`; Git Bash and PowerShell |
| Python | `3.11.4` in the local experiment; Python 3.11+ required; standard library only |
| Rust | `nightly-2025-05-13`: `rustc 1.89.0-nightly (8405332bd 2025-05-12)` |
| Cargo / Clippy | Cargo `1.89.0-nightly (056f5f4f3 2025-05-09)`; Clippy `0.1.88 (8405332bdf 2025-05-12)` |
| Measured Rust target | `x86_64-pc-windows-msvc` |
| C compiler available locally | MSYS2 UCRT64 GCC `13.2.0`; needed when the C oracle is used |
| Safety analyzer | Supplied `newmetrics` package, manifest version `0.1.0`, built with the pinned nightly |

The base model settings in [configs/model.json](configs/model.json) are temperature
`0.2`, top-p `0.95`, maximum completion `8192` tokens, thinking disabled, and a
`120`-second HTTP timeout. `max_retries: 2` means **two total HTTP attempts** in
this implementation. Retry backoff starts at 2 seconds; a requested wait above
20 seconds stops the request. No fallback model is configured. Focused Tester
analysis uses a smaller `1600`-token completion limit; effective limits are
recorded in the trajectory.

Tools available to agents include scoped file listing, search, reading and
writing, Cargo check/build/test/Clippy, the supplied newmetrics analyzer, and a
temporary C oracle. Rust implementations build independently and do not call the
original C through FFI. The original C project, required public interfaces, benchmark
test files, and Cargo manifests are preserved.

## Directory layout

```text
MP4/
  README.md
  configs/                  model settings, controller settings, and prompts
  src/                      controller, agents, harness, and safety adapter
  subjects/project_1/       original bigint C project and Rust template
  subjects/project_2/       original razz_simulation C project and Rust template
  translations/project_1/   final generated bigint crate
  translations/project_2/   final generated razz_simulation crate
  trajectories/project_1/   Project 1 experiment evidence
  trajectories/project_2/   Project 2 experiment evidence
  newmetrics/               supplied safety analyzer source
```

Local `backups/`, `runs/`, virtual environments, build caches, credentials, and
`MP4-local-history-*.zip` archives are ignored by Git.

## Installation

Run commands from the repository root unless another directory is specified.

### Python and model access

No third-party Python packages are required. A virtual environment is optional:

```powershell
python -m venv MP4/.venv
if (-not (Test-Path MP4/.env)) { Copy-Item MP4/.env.example MP4/.env }
```

Set `DEEPSEEK_API_KEY` in `MP4/.env`. The controller loads this file and preserves
an existing shell value if one is already set. Do not commit the private file.
Pipeline generation/repair commands use the configured provider and consume API
usage; the local Cargo and safety checks below do not call a model.

### Rust and native build tools

```powershell
rustup toolchain install nightly-2025-05-13 -c clippy,rustfmt
rustup component add rustc-dev llvm-tools-preview --toolchain nightly-2025-05-13
```

For the measured Windows MSVC target, install the Microsoft C++ build tools and
linker. The Windows runner can select `x86_64-pc-windows-gnu` if MSVC tools are
unavailable; that alternative additionally needs the GNU Rust target and MinGW.
The saved measurements use MSVC.

GCC or Clang must be on `PATH` when invoking the C oracle. The direct Python
controller uses `c_compiler: "cc"` from the configuration. The PowerShell
`run_all.ps1` wrapper checks for a C compiler and also searches the common
MSYS2 UCRT64/MinGW64 locations. Supplemental test generation is currently disabled,
so a direct run does not require a successful C oracle merely to proceed.

### Install the supplied newmetrics tool

The analyzer depends on the exact nightly compiler and its `rustc-dev` libraries.
Install both analyzer binaries with the pinned toolchain:

```powershell
cargo +nightly-2025-05-13 install --debug --locked --path MP4/newmetrics --force
```

**Windows compatibility.** The [wrapper source](newmetrics/src/bin/cargo-newmetrics.rs)
checks the compiler filename with `Path::file_stem`, recognizing both `rustc` and
Windows `rustc.exe`, including compiler paths. This carries the compatibility
adjustment used by the locally installed experiment tool into the source. It
affects invocation only; the metrics algorithm and translated program logic are
unchanged. Reinstall with the command above to rebuild the installed binaries
from this source.

The [safety adapter](src/safety_metrics.py) obtains the pinned sysroot, adds its
`bin` directory to the child process `PATH`, and checks the installed driver's
sysroot before analysis. This makes the matching `rustc_driver` DLL available to
the analyzer on Windows.

## Current configuration

The sources of truth are [pipeline.json](configs/pipeline.json),
[model.json](configs/model.json), and [prompts/](configs/prompts/).

| Setting | Current value |
| --- | --- |
| Toolchain | `nightly-2025-05-13` |
| Maximum outer iterations per invocation | `10` |
| Maximum provider HTTP requests per invocation, including retries | `80` |
| Maximum cumulative input + output tokens per invocation | `750000` |
| Repeated-failure stall threshold | `3` |
| Phase B modification attempts | `4` |
| Supplemental test-generation rounds | `0` |
| Safety backend / every-iteration measurement | `newmetrics` / `true` |
| Cargo / Cargo-test / safety timeout | `600` / `90` / `600` seconds |
| C-oracle execution timeout | `20` seconds |
| Actions per model reply / directory-search actions per agent invocation | `8` / `4` |
| Tool observation limit / retained conversation history | `6000` characters / `8` recent messages plus the initial system/task messages |

Configured role step ceilings are Reader `12`, Writer `15`, and Tester `8`.
Additional mode and provider-request limits reduce these ceilings:

| Role and mode | Reply ceiling before remaining-budget reductions | Additional source-read actions |
| --- | --- | --- |
| Reader, initial specification | `6`, from its request allowance | `18` |
| Reader, focused refresh | `4` | `4` |
| Writer, initial generation | `15` | `12` |
| Writer, focused repair | `15` | `16` |
| Writer, Phase B quality task | `15` | `12` |
| Tester, focused failure analysis | Up to `3` provider attempts | `16` |
| Tester, supplemental generation | `8`; disabled by current `tester_rounds: 0` | `24` |

Initial source packets are capped at 120,000 characters. After initial
implementation, compact Rust context is capped at 40,000 characters; focused
compiler-repair packets are capped at 48,000. Supplied source packets do not consume
read actions. Reader/analysis invocations reserve requests and tokens for Writer.
Each `agent_start` records the effective step, read and search limits.

Token accounting includes provider-reported cached input tokens. Before an HTTP
request, the controller estimates prompt usage with headroom and reserves completion
capacity, so it can stop before spending the exact token cap. A new invocation,
including `--continue`, starts a new request/token budget; saved iteration history
and the trajectory are retained. The current `tester_rounds: 0` setting applies to
Project 2's saved runs. Project 1's earlier checkpoint used `tester_rounds: 1` and
attempted supplemental generation without producing extra tests.

## Pipeline and stopping conditions

```text
Inspect C, Rust interfaces and provided tests
  -> Reader specifications
  -> Writer generates/modifies Rust
  -> compile and run tests
  -> return compiler, test and safety feedback
  -> analyze failures and repair
  -> repeat until the stopping condition
```

**Phase A** checks compilation, interfaces, and the provided tests plus any existing
extra tests. Compiler errors go directly to Writer. Behavioral failures are analyzed
by Tester and then routed to Writer; repeated failures can trigger Reader review.
With `tester_rounds: 0`, Tester still analyzes failures but is not required to create
new test files.

**Phase B** starts once interface and test checks pass. It returns Clippy and
newmetrics feedback for up to four quality-improvement attempts. Candidates that
break tests or fail to improve the metric score are reverted. A non-interrupted
final evaluation includes Clippy when the build succeeds, even if the run stops
in Phase A.

With the current configuration, successful-build evaluations run the supplied
newmetrics tool. Failed builds record safety analysis as `skipped`; an analyzer
failure is recorded as `failed`, not as zero unsafe counts. Agent-triggered
evaluations and the final evaluation can produce additional measurements beyond
the outer-iteration count.

Defined stopping conditions include zero quality score, exhausted Phase B attempts,
iteration/request/token limits, repeated stalls, evidenced `spec_gap`, missing
evidence, API errors, or user interruption. `phase_b_done` means the quality-attempt
limit was reached, not that all Clippy counts reached zero. A `spec_gap` currently
stops the entire run, including repairs to independent remaining issues.

The current initial-Writer gate requires both a source write and a completed
`done` in the same attempt. Project 2's initial invocation stopped at this gate
even though the modules had been generated and compiled. The documented
`--continue` invocation reused those files and entered the repair loop. This
controller limitation remains visible in the saved evidence.

The controller's process exit code alone does not establish experimental success;
inspect `final_status.json`, the test result, and analyzer status.

## Running the pipeline

### Both projects

From PowerShell at the repository root:

```powershell
.\MP4\src\run_all.ps1
```

The runner processes Project 1 and then Project 2. Existing generated crates are
resumed. `-Fresh` archives and regenerates both projects; `-MaxIterations` and
`-MaxLlmRequests` override their respective limits. To operate on only Project 2,
use its commands below.

### Project 1

For a new generation, archive the existing outputs and start from the template:

```bash
MP4/.venv/Scripts/python.exe -u MP4/src/pipeline.py \
  --project 1 \
  --c-dir MP4/subjects/project_1/bigint \
  --rust-template MP4/subjects/project_1/rust_template \
  --clean
```

Use `python` or the local environment's Python path on other platforms. To reproduce
the saved Project 1 configuration, use checkpoint `3d05f39`; its supplemental-test
setting differs from the current default.

### Project 2: the two saved invocations

Initial generation:

```bash
MP4/.venv/Scripts/python.exe -u MP4/src/pipeline.py \
  --project 2 \
  --c-dir MP4/subjects/project_2/razz_simulation \
  --rust-template MP4/subjects/project_2/rust_template \
  --clean
```

Continue from the generated implementation and saved specifications:

```bash
MP4/.venv/Scripts/python.exe -u MP4/src/pipeline.py \
  --project 2 \
  --c-dir MP4/subjects/project_2/razz_simulation \
  --rust-template MP4/subjects/project_2/rust_template \
  --continue
```

The two Project 2 invocations used the default 10-iteration, 80-request and
750,000-token limits. `--continue` skips initial generation and begins evaluation
of the existing Rust in Phase A; it does not restore a pending model conversation.
It requires an existing generated `src/` directory.

`--clean` first archives that project's current translation and trajectories under
`MP4/backups/project_<N>_<UTC timestamp>/`, excluding build caches, then copies the
supplied template and normalizes its interface-module layout. It starts a fresh
trajectory. `--clean` and `--continue` cannot be combined. A Project 2 command
operates on Project 2's output directories.

Other supported options include `--max-iterations`, `--max-llm-requests`,
`--cargo-target`, `--out-root`, and `--stop-after-tests`. The latter stops once
interface/tests and required safety analysis pass, before supplemental generation or
Phase B edits. The macOS/Linux wrapper is `src/run.sh`; it accepts project number,
C directory, Rust-template directory, and optional controller arguments.

## Saved experiment results

The results below are from the committed implementations, rather than earlier
checkpoints or discarded local reruns. The benchmark tests and Cargo manifests
match their supplied templates.

| Project | Compiles / interface check | Provided Cargo tests | Outer iterations | Final status |
| --- | --- | --- | --- | --- |
| 1: bigint | Pass / no missing signatures | `16/16` | `7` | `phase_b_done` |
| 2: razz_simulation | Pass / no missing signatures | `0/1` | `3` | `spec_gap` |

Project 1's Cargo layout runs **8 distinct test functions twice**, through binary
and integration targets, producing 16 executions. Project 2 has one aggregate
test containing many assertions. Its official Cargo result remains 0/1.

### Run IDs and usage

Run IDs use UTC. Local start times below use America/Chicago.

| Invocation | Run ID | Local start | HTTP requests | Input tokens | Output tokens | Total tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Project 1 | `20261114T051747_889357Z` | 2026-11-13 23:17 | 49 | 623,499 | 51,088 | 674,587 |
| Project 2, initial `--clean` | `20261114T070303_900705Z` | 2026-11-14 01:03 | 17 | 385,079 | 14,394 | 399,473 |
| Project 2, `--continue` | `20261114T070854_866086Z` | 2026-11-14 01:08 | 23 | 458,348 | 16,688 | 475,036 |
| Project 2, both invocations combined | — | — | 40 | 843,427 | 31,082 | 874,509 |

Project 2's initial invocation recorded zero outer iterations and stopped with
`evidence_required`. Its continuation recorded three iterations and stopped with
`spec_gap`. The current [Project 2 final status](trajectories/project_2/final_status.json)
contains **only the continuation's request/token usage**, while its trajectory
contains both invocations. Combined usage exceeds 750,000 tokens because the cap
is per invocation.

### Safety and Clippy

| Project | Unsafe lines | Unsafe calls | Unsafe casts | Pointer arithmetic | Clippy correctness | Style | Complexity | Perf |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Project 1 | 0 | 0 | 0 | 0 | 0 | 1 | 4 | 0 |
| Project 2 | 0 | 0 | 0 | 0 | 0 | 5 | 2 | 2 |

Both final safety analyses have `source: "newmetrics"`, `status: "ok"` and scope
`implementation-library`. Project 1 has 12 successful measurements, including
all seven outer iterations; Project 2 has six, including all three outer iterations
and measurements from initial generation and final evaluations. All primary counts
remain zero. Both final measurements also report zero raw-pointer declarations
and dereferences. This is a measured **zero-to-zero safety result**, not evidence
of an unsafe-to-safe reduction.

The adapter analyzes a temporary copy using `cargo check --lib`, the pinned
toolchain, an explicit target and a fresh `CARGO_TARGET_DIR`. It uses the supplied
wrapper through `RUSTC_WRAPPER`. Tests, benchmark binaries and dependencies are
excluded from the measured implementation scope. Hashes of tests and manifests
are also saved for provenance; their presence in metadata does not include them
in the unsafe counts. The built-in estimator remains a fallback in the harness
but was not the safety backend for these saved results.

Clippy categories are measured independently with `--all-targets --all-features`,
`-A clippy::all` and `-W clippy::<category>`. Counts deduplicate diagnostics by lint,
file, line and column. Ordinary Rust warnings, Cargo summaries and duplicate target
emissions are not additional Clippy findings. Raw JSONL logs are in `evaluations/`;
a file named `clippy.log` is not needed to interpret these records.

Project 1's Clippy total decreased from **8 to 5**. Two formatting diagnostics were
fixed; one `should_implement_trait` warning was suppressed with a local `allow`,
which is not an elimination of the underlying naming issue. The remaining five
findings are in unchanged benchmark tests. Its crate root has `#![forbid(unsafe_code)]`.

Project 2's final Clippy total is **9**: eight findings in the implementation and
one in the provided test. It stopped before Phase B, so these are final measurements,
not a completed Clippy-driven optimization pass. Neither project reached zero in
every Clippy category; structural inspection is also relevant to idiomaticity.

### Project 2 failure and remaining limitations

The final failure is `src/bin/test.rs:46`: actual `SpadeAce`, expected `Heart9`.
The source comparison shows a specific test-setup discrepancy:

- [C test](subjects/project_2/razz_simulation/card_test.c) line 317 removes
  `SPADE_ACE` after three insertions, then expects two remaining cards.
- The supplied [Rust test](subjects/project_2/rust_template/src/bin/test.rs)
  line 214 instead performs a fourth insertion into a full three-card hand,
  omits that removal, and still expects two cards at line 217.

The original tests were preserved. Following the team's clarification with the
professor, this inconsistency is documented rather than patched to force a pass.
See [the final failure analysis](trajectories/project_2/notes/failure_analysis.md).
This explains the particular failure above; it does not certify all other methods.

The implementation still resets the random seed to 3 on each
`create_shuffled_deck` call, which can repeat sequences across simulated games and
differs from preserving the C program's random stream. The public
`remove_from_hand_under_iter` helper has no direct operation; independent-call
behavior is not fully validated. These remain implementation limitations.

The separate diagnostic harness recorded 104,223 successful and 56 failed
assertion executions, across 104,279 executions. Those diagnostic counts are
not independent Cargo tests and must not be substituted for the official 0/1 result.

Project 1 attempted a C oracle for supplemental tests, but it failed because a
required process was not found; no extra Rust tests were completed. Project 2
disabled supplemental generation. Neither saved project has generated extra tests.

## Reading the evidence

Each project retains these files:

| Path under `trajectories/project_<N>/` | Meaning |
| --- | --- |
| `trajectory.jsonl` | Appended setup events, prompts, model replies, tools and repair decisions. Event `t` is elapsed time within its invocation. |
| `iterations.json` | Recorded outer evaluations; restored and extended by `--continue`. |
| `final_status.json` | Latest invocation's final result, stop reason and usage; overwritten on completion. |
| `notes/` | Reader specifications and Tester analyses; agent hypotheses should be checked against source. |
| `snapshots/original/` | Initial Rust-template source, not the original C project. |
| `snapshots/good/`, when present | Accepted Rust implementation used for regression rollback. |
| `evaluations/<run_id>/` | Evaluation JSON plus raw JSONL logs for the four Clippy categories. |
| `safety/<run_id>/<label>_<timestamp>/` | Supplied-tool safety measurement and its source fingerprints. |
| `assertion_diagnostics.tsv`, Project 2 | Additional assertion diagnostics, separate from official Cargo test counts. |

Each successful saved safety measurement contains `summary.json`, `metadata.json`, `newmetrics.log`,
`unsafe_spans.txt`, `decls.txt` and `derefs.txt`. The last three can be empty for a
successful zero-finding measurement; check `status` and the raw analyzer log.

Project 2 has **two run-ID directories in both `evaluations/` and `safety/`**:
one for initial generation and one for continuation. Each run can contain several
evaluations or safety measurements. Keep both directories with the combined trajectory.

Final summaries: [Project 1](trajectories/project_1/final_status.json) and
[Project 2](trajectories/project_2/final_status.json). Project 1 also retains
independent [build/test/Clippy review evidence](trajectories/project_1/review/verification.json).
The existing [idiomaticity report](idiomaticity_report.md) describes an older source
snapshot; its counts and deleted `translations/project_N/clippy.log` links do not
describe the current results. Use the current final summaries and `evaluations/`
logs when preparing the final progress report.

## Local evaluation without model calls

The saved artifacts already contain final evaluations. To independently check a
crate again, run these commands in `MP4/translations/project_1` or `project_2`:

```bash
cargo +nightly-2025-05-13 build
cargo +nightly-2025-05-13 test
cargo +nightly-2025-05-13 clippy --all-targets --all-features -- \
  -W clippy::correctness \
  -W clippy::style \
  -W clippy::complexity \
  -W clippy::perf
```

A standalone supplied-tool measurement can also be run from the repository root,
replacing `project_1` with `project_2` as needed:

```bash
python MP4/src/safety_metrics.py \
  --crate MP4/translations/project_1 \
  --output MP4/runs/manual_safety/project_1 \
  --toolchain nightly-2025-05-13
```

This writes a new timestamped measurement under the chosen output directory.
The course's MP4 validation script is not currently included in this checkout;
run the instructional team's script before submission when available. Passing
structural validation does not establish functional correctness.

The logger redacts configured key values and common token formats. Review new
trajectories before committing, and keep credentials, local backups and build
artifacts out of the submission. The final progress report should use the current
results and explain test discrepancies, unsuccessful repairs and remaining limits.

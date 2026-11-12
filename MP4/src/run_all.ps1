param(
    [int]$MaxIterations = 0,
    [int]$MaxLlmRequests = 0,
    [switch]$Fresh
)

$ErrorActionPreference = "Stop"

$mp4Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$modelConfigPath = Join-Path $mp4Root "configs\model.json"
$pipelineConfigPath = Join-Path $mp4Root "configs\pipeline.json"
$modelConfig = Get-Content -LiteralPath $modelConfigPath -Raw | ConvertFrom-Json
$pipelineConfig = Get-Content -LiteralPath $pipelineConfigPath -Raw | ConvertFrom-Json
$python = Get-Command python -ErrorAction SilentlyContinue
$rustup = Get-Command rustup -ErrorAction SilentlyContinue

if (-not $python) { throw "Python was not found. Install Python 3 and add python.exe to PATH." }
if (-not $rustup) { throw "rustup was not found. Install Rust with rustup and add it to PATH." }
if (-not (Get-Command ([string]$pipelineConfig.c_compiler) -ErrorAction SilentlyContinue)) {
    throw "C compiler '$($pipelineConfig.c_compiler)' was not found. Install GCC/Clang and add it to PATH."
}

$toolchain = [string]$pipelineConfig.toolchain
$installedToolchains = & $rustup.Source toolchain list
if ($LASTEXITCODE -ne 0 -or -not ($installedToolchains -match "^$([regex]::Escape($toolchain))")) {
    throw "Rust toolchain $toolchain is missing. Install it with: rustup toolchain install $toolchain -c clippy,rustfmt"
}
$components = & $rustup.Source component list --installed --toolchain $toolchain
if ($LASTEXITCODE -ne 0 -or -not ($components -match "(?m)^clippy-")) {
    throw "Clippy is missing from $toolchain. Install it with: rustup component add clippy --toolchain $toolchain"
}

$keyName = [string]$modelConfig.api_key_env
$keyValue = [Environment]::GetEnvironmentVariable($keyName)
if ([string]::IsNullOrWhiteSpace($keyValue)) {
    $envFile = Join-Path $mp4Root ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match "^\s*$([regex]::Escape($keyName))\s*=\s*(.*?)\s*$") {
                $keyValue = $Matches[1].Trim()
                if ($keyValue.Length -ge 2 -and
                    (($keyValue.StartsWith('"') -and $keyValue.EndsWith('"')) -or
                     ($keyValue.StartsWith("'") -and $keyValue.EndsWith("'")))) {
                    $keyValue = $keyValue.Substring(1, $keyValue.Length - 2)
                }
                break
            }
        }
    }
}
if ([string]::IsNullOrWhiteSpace($keyValue) -or $keyValue -match "^(?i:your[-_].*|<.*>)$") {
    throw "Model credentials are missing. Copy MP4/.env.example to MP4/.env and set $keyName."
}

$platformArgs = @()
if ($env:OS -eq "Windows_NT") {
    $hasMsvc = (Get-Command cl.exe -ErrorAction SilentlyContinue) -and
        (Get-Command link.exe -ErrorAction SilentlyContinue)
    if (-not $hasMsvc) {
        $installedTargets = & $rustup.Source target list --installed --toolchain $toolchain
        if ($LASTEXITCODE -ne 0 -or -not ($installedTargets -contains "x86_64-pc-windows-gnu")) {
            throw "Neither MSVC tools nor the GNU Rust target are ready. Install the GNU target and MinGW, or use a Visual Studio Developer shell."
        }
        $platformArgs = @("--cargo-target", "x86_64-pc-windows-gnu")
    }
}

$projects = @(
    @{ Number = 1; CDir = "subjects/project_1/bigint"; Template = "subjects/project_1/rust_template" },
    @{ Number = 2; CDir = "subjects/project_2/razz_simulation"; Template = "subjects/project_2/rust_template" }
)

Push-Location $mp4Root
try {
    foreach ($project in $projects) {
        $cDir = Join-Path $mp4Root $project.CDir.Replace('/', '\')
        $template = Join-Path $mp4Root $project.Template.Replace('/', '\')
        if (-not (Test-Path -LiteralPath $cDir -PathType Container)) {
            throw "Project $($project.Number) C source directory is missing: $cDir"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $template "Cargo.toml") -PathType Leaf)) {
            throw "Project $($project.Number) CRUST Rust template is missing: $template"
        }

        $pythonArgs = @(
            "-u", "src/pipeline.py",
            "--project", [string]$project.Number,
            "--c-dir", $project.CDir,
            "--rust-template", $project.Template
        )
        if ($Fresh) {
            $pythonArgs += "--clean"
        } elseif (Test-Path -LiteralPath (Join-Path $mp4Root "translations\project_$($project.Number)\src") -PathType Container) {
            $pythonArgs += "--resume"
        }
        if ($MaxIterations -gt 0) {
            $pythonArgs += @("--max-iterations", [string]$MaxIterations)
        }
        if ($MaxLlmRequests -gt 0) {
            $pythonArgs += @("--max-llm-requests", [string]$MaxLlmRequests)
        }
        $pythonArgs += $platformArgs

        Write-Host "Starting Project $($project.Number) ..."
        & $python.Source @pythonArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Project $($project.Number) controller exited with code $LASTEXITCODE."
        }

        $statusPath = Join-Path $mp4Root "trajectories\project_$($project.Number)\final_status.json"
        if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
            throw "Project $($project.Number) did not produce final_status.json."
        }
        $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $testSummary = "n/a"
        if ($status.core) { $testSummary = "$($status.core.passed)/$($status.core.total)" }
        Write-Host "Project $($project.Number): status=$($status.status), build_ok=$($status.build_ok), tests=$testSummary"
        if ([string]$status.status -like "llm_error:*") {
            throw "Project $($project.Number) stopped on an API error; fix model access before continuing."
        }
    }
} finally {
    Pop-Location
}

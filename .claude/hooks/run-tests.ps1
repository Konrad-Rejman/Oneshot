# PostToolUse hook: run the pytest suite after Claude edits/writes a project .py file.
# Exit 0 = pass or not applicable; exit 2 = tests failed (stderr is fed back to Claude).
$project = 'W:\Oneshot\Oneshot'

try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
} catch { exit 0 }

$filePath = $null
if ($payload -and $payload.tool_input) { $filePath = $payload.tool_input.file_path }
if (-not $filePath) { exit 0 }

$normalized = $filePath -replace '/', '\'
if ($normalized -notmatch '\.py$') { exit 0 }
if ($normalized -match '\\\.venv312\\') { exit 0 }
if (-not $normalized.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) { exit 0 }

$python = Join-Path $project '.venv312\Scripts\python.exe'
$output = & $python -m pytest (Join-Path $project 'tests') -q

if ($LASTEXITCODE -ne 0) {
    $tail = ($output | Select-Object -Last 30) -join "`n"
    [Console]::Error.WriteLine("pytest failed (exit $LASTEXITCODE) after editing $filePath`:`n$tail")
    exit 2
}
exit 0

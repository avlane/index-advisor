# Weekly index review for a Windows scheduled task or a SQL Agent PowerShell step.
#
# Keeps a usage history between runs (so restarts do not hide how an index is used), writes the
# report and the review scripts to a dated folder, and returns index-advisor's exit code: with
# --exit-code that is 1 when there is something to drop or consolidate.
# Adjust the paths; index-advisor must be on the PATH of the account running the job.
param(
    [string]$Server = "SQLPROD01",
    [string]$Root = "D:\Reports\index-advisor"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd"
$out = Join-Path $Root $stamp
New-Item -ItemType Directory -Force -Path $out | Out-Null

index-advisor --server $Server `
    --config "$PSScriptRoot\advisor.toml" `
    --history "$Root\$Server.history.json" `
    --format markdown --output "$out\review.md" `
    --scripts-dir "$out\scripts" `
    --exit-code

exit $LASTEXITCODE

$ErrorActionPreference = 'Stop'

# このスクリプトはレポートの保存以外に、予測・モデル・ダッシュボードを変更しない。
$root = (Get-Location).Path
$root = (Get-Location).Path
$promptPath = Join-Path $root 'codex_prediction_review_prompt.txt'
$reportsDir = Join-Path $root 'reports'
$outputPath = Join-Path $reportsDir 'codex_prediction_review_latest.md'

Write-Host ''
Write-Host '===== Codex prediction review ====='
Write-Host 'This run is read-only. It will not change models, predictions, or dashboard files.'
Write-Host ''

try {
    if (-not (Test-Path -LiteralPath $promptPath)) {
        throw 'The review prompt file was not found.'
    }

    # 公式インストーラーの標準パスを優先し、Storeアプリの実行エイリアスを避ける。
    $codexExe = Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin\codex.exe'
    $codexExe = Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin\codex.exe'
    if (-not (Test-Path -LiteralPath $codexExe)) {
        throw 'Codex CLI was not found. Open the Codex app once and sign in, then try again.'
    }

    New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null
    Get-Content -LiteralPath $promptPath -Raw -Encoding UTF8 |
        & $codexExe --sandbox read-only --ask-for-approval never exec --output-last-message $outputPath -

    if ($LASTEXITCODE -ne 0) {
        throw "Codex finished with exit code $LASTEXITCODE."
    }

    Write-Host ''
    Write-Host 'Done.'
    Write-Host "Report: $outputPath"
}
catch {
    Write-Host ''
    Write-Host "[ERROR] $($_.Exception.Message)"
    Write-Host 'Check that Codex is signed in and that your Codex usage is available.'
    exit 1
}

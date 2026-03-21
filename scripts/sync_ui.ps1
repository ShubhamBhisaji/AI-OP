$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot 'AetheerAI\ui'
$targetDir = Join-Path $repoRoot 'ui'
$files = @('index.html', 'styles.css', 'app.js')

if (-not (Test-Path $sourceDir)) {
    throw "Source UI directory not found: $sourceDir"
}

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir | Out-Null
}

foreach ($file in $files) {
    $sourcePath = Join-Path $sourceDir $file
    $targetPath = Join-Path $targetDir $file

    if (-not (Test-Path $sourcePath)) {
        throw "Missing source file: $sourcePath"
    }

    Copy-Item -Path $sourcePath -Destination $targetPath -Force
    Write-Host "Synced $file"
}

Write-Host "UI mirror updated from AetheerAI/ui -> ui"
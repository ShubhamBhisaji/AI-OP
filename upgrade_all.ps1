$packages = @(
    "Git.Git",
    "VideoLAN.VLC",
    "OpenJS.NodeJS.22",
    "Microsoft.VisualStudioCode",
    "Microsoft.VCRedist.x64.14",
    "Microsoft.VCRedist.x86.14",
    "GitHub.GitHubDesktop",
    "Ollama.Ollama",
    "Microsoft.Teams",
    "Microsoft.WSL",
    "Docker.DockerDesktop"
)

$log = "C:\Users\Tecbunny Solutions\Downloads\AI-OP\upgrade_log.txt"
"=== Upgrade started: $(Get-Date) ===" | Out-File $log

foreach ($pkg in $packages) {
    ">>> Upgrading $pkg at $(Get-Date)" | Tee-Object -Append $log
    winget upgrade $pkg --accept-source-agreements --accept-package-agreements 2>&1 | Tee-Object -Append $log
    "" | Out-File -Append $log
}

"=== Upgrade completed: $(Get-Date) ===" | Tee-Object -Append $log

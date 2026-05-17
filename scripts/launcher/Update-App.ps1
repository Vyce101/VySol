Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootPath = Resolve-Path (Join-Path $scriptPath "..\..")
$runtimePath = Join-Path $rootPath "runtime"
$logPath = Join-Path $runtimePath "logs"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logPath "update_$timestamp.log"

New-Item -ItemType Directory -Force -Path $logPath | Out-Null

function Write-UpdateLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet("INFO", "WARNING", "ERROR")][string]$Level = "INFO"
    )

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Assert-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Command)

    if ($null -eq (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Missing dependency: command '$Command' was not found. Install it, then run update.bat again."
    }
}

try {
    Write-UpdateLog "Checking for VySol updates in $rootPath"
    Set-Location $rootPath
    Assert-CommandAvailable -Command "git"

    $insideWorkTree = git rev-parse --is-inside-work-tree
    if ($insideWorkTree -ne "true") {
        throw "This folder is not a git repository."
    }

    $branch = git branch --show-current
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw "Unable to determine the current git branch."
    }

    $status = git status --short
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        Write-UpdateLog "Local changes are present. Git will refuse unsafe overwrites if the update conflicts." "WARNING"
    }

    git fetch --prune origin
    $upstream = "origin/$branch"
    git rev-parse --verify $upstream | Out-Null
    $changedFiles = git diff --name-only HEAD..$upstream

    if ([string]::IsNullOrWhiteSpace($changedFiles)) {
        Write-UpdateLog "No remote file changes found for $upstream."
        Write-UpdateLog "Update complete. Close this window, then start the app with run.bat."
        exit 0
    }

    Write-UpdateLog "Files that differ from ${upstream}:"
    $changedFiles -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object {
        Write-UpdateLog "  $_"
    }

    git pull --ff-only origin $branch
    Write-UpdateLog "Update complete. This script does not start the app."
    Write-UpdateLog "Close this window, then start the app with run.bat."
}
catch {
    Write-UpdateLog $_.Exception.Message "ERROR"
    Write-UpdateLog "Update stopped. Resolve the message above, then run update.bat again." "ERROR"
    exit 1
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootPath = Resolve-Path (Join-Path $scriptPath "..\..")
$configPath = Join-Path $scriptPath "launcher.config.json"
$pythonPath = Join-Path $rootPath ".venv\Scripts\python.exe"
$requirementsPath = Join-Path $rootPath "requirements.txt"
$runtimePath = Join-Path $rootPath "runtime"
$logPath = Join-Path $runtimePath "logs"
$statePath = Join-Path $runtimePath "state"
$stateFile = Join-Path $statePath "app-processes.json"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logPath "launcher_$timestamp.log"

New-Item -ItemType Directory -Force -Path $logPath, $statePath | Out-Null

function Write-LauncherLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet("INFO", "WARNING", "ERROR")][string]$Level = "INFO"
    )

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    $line | Tee-Object -FilePath $logFile -Append
}

function Read-Config {
    if (-not (Test-Path $configPath)) {
        throw "Missing launcher config: $configPath"
    }

    return Get-Content $configPath -Raw | ConvertFrom-Json
}

function Assert-PythonVirtualEnvironment {
    if (-not (Test-Path $pythonPath)) {
        throw "Missing project virtual environment Python: .venv\Scripts\python.exe"
    }

    if (-not (Test-Path $requirementsPath)) {
        throw "Missing backend requirements file: requirements.txt"
    }
}

function Read-PinnedRequirements {
    $requirements = @()
    $lines = Get-Content $requirementsPath

    foreach ($line in $lines) {
        $trimmedLine = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmedLine) -or $trimmedLine.StartsWith("#")) {
            continue
        }

        $parts = $trimmedLine -split [regex]::Escape("=="), 2
        if ($parts.Count -ne 2) {
            throw "Requirement '$trimmedLine' must use an exact == version pin."
        }

        $requirements += [pscustomobject]@{
            Name = [string]$parts[0]
            Version = [string]$parts[1]
        }
    }

    return $requirements
}

function Test-PinnedRequirementInstalled {
    param([Parameter(Mandatory = $true)]$Requirement)

    $packageInfo = & $pythonPath -m pip show ([string]$Requirement.Name) 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($packageInfo)) {
        return $false
    }

    $versionLine = $packageInfo | Where-Object { $_.StartsWith("Version:") } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($versionLine)) {
        return $false
    }

    $installedVersion = $versionLine.Substring("Version:".Length).Trim()
    return $installedVersion -eq ([string]$Requirement.Version)
}

function Install-MissingPythonDependencies {
    Assert-PythonVirtualEnvironment
    $requirements = Read-PinnedRequirements
    $missingRequirements = @()

    foreach ($requirement in $requirements) {
        if (-not (Test-PinnedRequirementInstalled -Requirement $requirement)) {
            $missingRequirements += "$($requirement.Name)==$($requirement.Version)"
        }
    }

    if ($missingRequirements.Count -eq 0) {
        Write-LauncherLog "Python dependencies are already installed."
        return
    }

    Write-LauncherLog "Installing missing Python dependencies: $($missingRequirements -join ', ')"
    & $pythonPath -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed."
    }
}

function Get-CommandLineByPid {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return ""
    }

    return [string]$process.CommandLine
}

function Get-ListeningProcessOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }

    $pidValue = [int]$connection.OwningProcess
    return [pscustomobject]@{
        ProcessId = $pidValue
        CommandLine = Get-CommandLineByPid -ProcessId $pidValue
    }
}

function Resolve-ServiceCommand {
    param([Parameter(Mandatory = $true)][string]$Command)

    $repoRelativeCommand = Join-Path $rootPath $Command
    if (Test-Path $repoRelativeCommand) {
        return (Resolve-Path $repoRelativeCommand).Path
    }

    $resolvedCommand = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -eq $resolvedCommand) {
        throw "Missing dependency: command '$Command' was not found. Install it or update scripts/launcher/launcher.config.json."
    }

    return $resolvedCommand.Source
}

function Test-IsAppOwned {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }

    $normalizedCommand = $CommandLine.ToLowerInvariant()
    $normalizedRoot = ([string]$Record.rootPath).ToLowerInvariant()
    $fingerprint = ([string]$Record.commandFingerprint).ToLowerInvariant()

    return $normalizedCommand.Contains($normalizedRoot) -and $normalizedCommand.Contains($fingerprint)
}

function Get-ChildProcessIds {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        [int]$child.ProcessId
        Get-ChildProcessIds -ProcessId ([int]$child.ProcessId)
    }
}

function Stop-AppOwnedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $ids = @(Get-ChildProcessIds -ProcessId $ProcessId) + @($ProcessId)
    foreach ($id in ($ids | Select-Object -Unique | Sort-Object -Descending)) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }

        Write-LauncherLog "Stopping app-owned process $id ($Reason)."
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}

function Stop-AppOwnedRecord {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)][string]$Reason,
        [bool]$TrustRecordedPids = $false
    )

    $pidValue = [int]$Record.processId
    $commandLine = Get-CommandLineByPid -ProcessId $pidValue
    if ($TrustRecordedPids -or (Test-IsAppOwned -Record $Record -CommandLine $commandLine)) {
        Stop-AppOwnedProcess -ProcessId $pidValue -Reason $Reason
    }

    if ($Record.actualListeningProcessId) {
        $listeningPid = [int]$Record.actualListeningProcessId
        $listeningCommandLine = Get-CommandLineByPid -ProcessId $listeningPid
        if ($TrustRecordedPids -or (Test-IsAppOwned -Record $Record -CommandLine $listeningCommandLine)) {
            Stop-AppOwnedProcess -ProcessId $listeningPid -Reason "$Reason recorded listener"
        }
    }

    if ($Record.requiredPort) {
        $owner = Get-ListeningProcessOnPort -Port ([int]$Record.requiredPort)
        if ($null -ne $owner -and (Test-IsAppOwned -Record $Record -CommandLine $owner.CommandLine)) {
            Stop-AppOwnedProcess -ProcessId $owner.ProcessId -Reason "$Reason port listener"
        }
    }
}

function Read-StateRecords {
    if (-not (Test-Path $stateFile)) {
        return ,@()
    }

    $content = Get-Content $stateFile -Raw
    if ([string]::IsNullOrWhiteSpace($content)) {
        return ,@()
    }

    $records = $content | ConvertFrom-Json
    if ($null -eq $records) {
        return ,@()
    }

    return @($records)
}

function Write-StateRecords {
    param([array]$Records = @())

    $Records | ConvertTo-Json -Depth 8 | Set-Content -Path $stateFile
}

function Stop-StaleAppOwnedProcesses {
    $records = Read-StateRecords
    foreach ($record in $records) {
        $pidValue = [int]$record.processId
        $commandLine = Get-CommandLineByPid -ProcessId $pidValue
        Stop-AppOwnedRecord -Record $record -Reason "stale process from prior run"
    }

    Write-StateRecords -Records @()
}

function Assert-ServiceCanStart {
    param([Parameter(Mandatory = $true)]$Service)

    $workingDirectory = Join-Path $rootPath ([string]$Service.workingDirectory)
    if (-not (Test-Path $workingDirectory)) {
        throw "Missing working directory for service '$($Service.name)': $workingDirectory"
    }

    Resolve-ServiceCommand -Command ([string]$Service.command) | Out-Null
}

function Assert-PortAvailableOrRecoverAppOwned {
    param(
        [Parameter(Mandatory = $true)]$Service,
        [AllowEmptyCollection()]
        [Parameter(Mandatory = $true)][array]$KnownRecords
    )

    if (-not $Service.requiredPort) {
        return
    }

    $port = [int]$Service.requiredPort
    $owner = Get-ListeningProcessOnPort -Port $port
    if ($null -eq $owner) {
        return
    }

    $record = $KnownRecords | Where-Object { [int]$_.requiredPort -eq $port } | Select-Object -First 1
    if ($null -ne $record -and (Test-IsAppOwned -Record $record -CommandLine $owner.CommandLine)) {
        Stop-AppOwnedProcess -ProcessId $owner.ProcessId -Reason "recovering app-owned port $port"
        return
    }

    throw "Port $port is already in use by PID $($owner.ProcessId). Command line: $($owner.CommandLine). Close that program or change the launcher config."
}

function Start-ServiceProcess {
    param([Parameter(Mandatory = $true)]$Service)

    $workingDirectory = Resolve-Path (Join-Path $rootPath ([string]$Service.workingDirectory))
    $stdoutLog = Join-Path $logPath "$($Service.name)_$timestamp.stdout.log"
    $stderrLog = Join-Path $logPath "$($Service.name)_$timestamp.stderr.log"
    $command = Resolve-ServiceCommand -Command ([string]$Service.command)

    Write-LauncherLog "Starting $($Service.name): $command $($Service.arguments -join ' ')"
    $process = Start-Process -FilePath $command -ArgumentList @($Service.arguments) -WorkingDirectory $workingDirectory -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru -WindowStyle Hidden

    return [pscustomobject]@{
        serviceName = [string]$Service.name
        processId = [int]$process.Id
        rootPath = [string]$rootPath
        requiredPort = $Service.requiredPort
        commandFingerprint = [string]$Service.commandFingerprint
        command = [string]$Service.command
        arguments = @($Service.arguments)
        actualListeningProcessId = $null
        logFiles = @($stdoutLog, $stderrLog)
        startedAt = (Get-Date).ToString("o")
    }
}

function Test-HealthReady {
    param([Parameter(Mandatory = $true)][string]$HealthUrl)

    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-ForReadiness {
    param(
        [Parameter(Mandatory = $true)][array]$Services,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $notReady = @()
        foreach ($service in $Services) {
            if (-not $service.healthUrl) {
                continue
            }

            if (-not (Test-HealthReady -HealthUrl ([string]$service.healthUrl))) {
                $notReady += [string]$service.name
            }
        }

        if ($notReady.Count -eq 0) {
            return
        }

        Start-Sleep -Seconds 1
    }

    throw "Readiness timed out after $TimeoutSeconds seconds."
}

function Update-ListeningProcessRecords {
    param([Parameter(Mandatory = $true)][array]$Records)

    foreach ($record in $Records) {
        if (-not $record.requiredPort) {
            continue
        }

        $owner = Get-ListeningProcessOnPort -Port ([int]$record.requiredPort)
        if ($null -eq $owner) {
            continue
        }

        $record.actualListeningProcessId = [int]$owner.ProcessId
        Write-LauncherLog "Recorded $($record.serviceName) listener PID $($owner.ProcessId) on port $($record.requiredPort)."
    }
}

function Show-LogTailUntilExit {
    param([Parameter(Mandatory = $true)][array]$Records)

    Write-LauncherLog "App is ready. Press Q in this window to shut down app-owned processes."
    $offsets = @{}
    foreach ($record in $Records) {
        foreach ($logFilePath in @($record.logFiles)) {
            $offsets[[string]$logFilePath] = 0
        }
    }

    while ($true) {
        foreach ($record in $Records) {
            foreach ($logFilePath in @($record.logFiles)) {
                $path = [string]$logFilePath
                if (-not (Test-Path $path)) {
                    continue
                }

                $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                try {
                    $stream.Seek([int64]$offsets[$path], [System.IO.SeekOrigin]::Begin) | Out-Null
                    $reader = New-Object System.IO.StreamReader($stream)
                    $newText = $reader.ReadToEnd()
                    $offsets[$path] = $stream.Position
                    if (-not [string]::IsNullOrWhiteSpace($newText)) {
                        Write-Host $newText -NoNewline
                    }
                }
                finally {
                    $stream.Dispose()
                }
            }
        }

        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq [ConsoleKey]::Q) {
                return
            }
        }

        $alive = $false
        foreach ($record in $Records) {
            if ($null -ne (Get-Process -Id ([int]$record.processId) -ErrorAction SilentlyContinue)) {
                $alive = $true
                break
            }
        }

        if (-not $alive) {
            throw "All app-owned processes exited."
        }

        Start-Sleep -Milliseconds 500
    }
}

$startedRecords = @()

try {
    Write-LauncherLog "Starting VySol launcher from $rootPath"
    $config = Read-Config
    $enabledServices = @($config.services | Where-Object { $_.enabled -eq $true })

    Install-MissingPythonDependencies
    Stop-StaleAppOwnedProcesses

    if ($enabledServices.Count -eq 0) {
        Write-LauncherLog "No launcher services are enabled yet. Update scripts/launcher/launcher.config.json after the app startup contract is stable." "WARNING"
        Write-LauncherLog "TODOs: $($config.todos -join '; ')" "WARNING"
        exit 2
    }

    $knownRecords = Read-StateRecords
    foreach ($service in $enabledServices) {
        Assert-ServiceCanStart -Service $service
    }

    foreach ($service in $enabledServices) {
        Assert-PortAvailableOrRecoverAppOwned -Service $service -KnownRecords $knownRecords
    }

    foreach ($service in $enabledServices) {
        $startedRecords += Start-ServiceProcess -Service $service
        Write-StateRecords -Records $startedRecords
    }

    Wait-ForReadiness -Services $enabledServices -TimeoutSeconds ([int]$config.readyTimeoutSeconds)
    Update-ListeningProcessRecords -Records $startedRecords
    Write-StateRecords -Records $startedRecords
    Start-Process ([string]$config.browserUrl)
    Show-LogTailUntilExit -Records $startedRecords
}
catch {
    Write-LauncherLog $_.Exception.Message "ERROR"
    foreach ($record in $startedRecords) {
        Stop-AppOwnedRecord -Record $record -Reason "startup failure or shutdown" -TrustRecordedPids $true
    }
    Write-StateRecords -Records @()
    exit 1
}
finally {
    foreach ($record in $startedRecords) {
        Stop-AppOwnedRecord -Record $record -Reason "launcher shutdown" -TrustRecordedPids $true
    }
    Write-StateRecords -Records @()
}

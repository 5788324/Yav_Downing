param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$root = Join-Path $env:RUNNER_TEMP 'yav-rc5-final'
$data = Join-Path $root 'data'
$migrationData = Join-Path $root 'migration-data'
$site = Join-Path $root 'site'
$report = Join-Path $env:RUNNER_TEMP 'rc5-final-report.txt'
$port = 18765
$sitePort = 18766

Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $report -Force -ErrorAction SilentlyContinue
New-Item $data, $migrationData, $site -ItemType Directory -Force | Out-Null
Set-Content (Join-Path $site 'index.html') '<html><body>local JPHOO smoke</body></html>'

function Write-Report([string]$Text) {
    $line = "$(Get-Date -Format o) $Text"
    Write-Host $line
    Add-Content $report $line
}

function Start-Yav([string[]]$Arguments, [bool]$CleanEnvironment = $false) {
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $exe
    foreach ($argument in $Arguments) {
        [void]$psi.ArgumentList.Add($argument)
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    if ($CleanEnvironment) {
        $psi.Environment.Clear()
        $psi.Environment['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem;$env:ProgramFiles\Microsoft\Edge\Application"
        foreach ($name in @(
            'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE',
            'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'PROGRAMFILES',
            'HOMEDRIVE', 'HOMEPATH'
        )) {
            $value = [Environment]::GetEnvironmentVariable($name)
            if ($value) {
                $psi.Environment[$name] = $value
            }
        }
        $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
        if ($programFilesX86) {
            $psi.Environment['ProgramFiles(x86)'] = $programFilesX86
        }
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        throw 'Process.Start returned false'
    }
    return $process
}

function Wait-Yav([int]$ExpectedPort = $port, [int]$TimeoutSeconds = 45) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $status = Invoke-RestMethod "http://127.0.0.1:$ExpectedPort/api/app/status" -TimeoutSec 2
            if ($status.app -eq 'Yav') {
                return $status
            }
        }
        catch {}
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Yav readiness timeout on port $ExpectedPort"
}

function Run-Yav([string[]]$Arguments, [int]$TimeoutMilliseconds = 60000) {
    $process = Start-Yav $Arguments $false
    if (-not $process.WaitForExit($TimeoutMilliseconds)) {
        $process.Kill($true)
        throw "Yav command timeout: $($Arguments -join ' ')"
    }
    if ($process.ExitCode -ne 0) {
        throw "Yav command exit $($process.ExitCode): $($Arguments -join ' ')"
    }
}

function Assert-PortClosed([int]$ExpectedPort = $port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $client.Connect('127.0.0.1', $ExpectedPort)
        throw "Port $ExpectedPort is still open"
    }
    catch [System.Net.Sockets.SocketException] {
        return
    }
    finally {
        $client.Dispose()
    }
}

function Assert-NoRuntimeFiles([string]$DataDir) {
    foreach ($relative in @(
        'runtime\instance.json',
        'runtime\shutdown.secret',
        'runtime\instance.lock'
    )) {
        if (Test-Path (Join-Path $DataDir $relative)) {
            throw "Runtime residue: $relative"
        }
    }
}

$server = $null
$http = $null
$stage = 'setup'
try {
    $stage = 'local-site'
    Write-Report "STAGE=$stage"
    $http = Start-Process python -ArgumentList @(
        '-m', 'http.server', "$sitePort", '--bind', '127.0.0.1', '--directory', $site
    ) -PassThru -WindowStyle Hidden

    $stage = 'clean-start'
    Write-Report "STAGE=$stage"
    $server = Start-Yav @('--data-dir', $data, '--port', "$port", '--no-browser') $true
    $status = Wait-Yav
    Write-Report "READY version=$($status.version) pid=$($status.pid)"
    if ($status.version -ne '2.0.0-rc5') {
        throw "Wrong version: $($status.version)"
    }
    if (-not (Test-Path (Join-Path $data 'library.db'))) {
        throw 'library.db was not created'
    }
    Invoke-RestMethod "http://127.0.0.1:$port/api/filters" | Out-Null
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
        throw "Unexpected listener set: $($listeners | ConvertTo-Json -Compress)"
    }

    $stage = 'edge-open'
    Write-Report "STAGE=$stage"
    $series = Invoke-RestMethod -Method Post "http://127.0.0.1:$port/api/sources/jphoo" `
        -ContentType 'application/json' `
        -Body (@{ name = 'CI'; url = "http://127.0.0.1:$sitePort/"; enabled = $true } | ConvertTo-Json)
    Invoke-RestMethod -Method Post "http://127.0.0.1:$port/api/sources/jphoo/login/open" `
        -ContentType 'application/json' `
        -Body (@{ series_id = $series.id } | ConvertTo-Json) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $jphoo = Invoke-RestMethod "http://127.0.0.1:$port/api/sources/jphoo/login"
    } while (
        $jphoo.status -notin @('window_open', 'ready', 'failed') -and
        [DateTime]::UtcNow -lt $deadline
    )
    Write-Report "EDGE_STATUS=$($jphoo.status) message=$($jphoo.message)"
    if ($jphoo.status -notin @('window_open', 'ready')) {
        throw "Edge state $($jphoo.status): $($jphoo.message)"
    }
    $profile = Join-Path $data 'browser-profile\jphoo'
    $profilePattern = [regex]::Escape($profile)
    $edgeCount = @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -match $profilePattern }
    ).Count
    Write-Report "EDGE_COUNT=$edgeCount"
    if ($edgeCount -lt 1) {
        throw 'Yav profile Edge process was not found'
    }

    $stage = 'api-shutdown'
    Write-Report "STAGE=$stage"
    $pageHtml = (Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing).Content
    $bootstrapMatch = [regex]::Match(
        $pageHtml,
        'window\.__YAV_BOOTSTRAP__\s*=\s*(\{[^;]+\});'
    )
    if (-not $bootstrapMatch.Success) {
        throw 'Shutdown bootstrap was not found'
    }
    $bootstrap = $bootstrapMatch.Groups[1].Value | ConvertFrom-Json
    $shutdownResponse = Invoke-WebRequest -Method Post `
        "http://127.0.0.1:$port/api/app/shutdown" `
        -Headers @{ Origin = "http://127.0.0.1:$port" } `
        -ContentType 'application/json' `
        -Body (@{
            token = $bootstrap.shutdownToken
            instance_id = $bootstrap.instanceId
        } | ConvertTo-Json) `
        -UseBasicParsing
    Write-Report "SHUTDOWN_HTTP=$($shutdownResponse.StatusCode)"
    if ($shutdownResponse.StatusCode -ne 202) {
        throw 'Shutdown endpoint did not return 202'
    }
    if (-not $server.WaitForExit(45000)) {
        throw 'API shutdown process timeout'
    }
    Start-Sleep -Seconds 2
    Assert-PortClosed
    Assert-NoRuntimeFiles $data
    $edgeAfter = @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -match $profilePattern }
    ).Count
    Write-Report "API_EXIT=$($server.ExitCode) EDGE_AFTER=$edgeAfter"
    if ($edgeAfter -ne 0) {
        throw "Edge residue after API shutdown: $edgeAfter"
    }

    $stage = 'cli-shutdown'
    Write-Report "STAGE=$stage"
    $server = Start-Yav @('--data-dir', $data, '--port', "$port", '--no-browser') $true
    Wait-Yav | Out-Null
    Run-Yav @('--data-dir', $data, '--shutdown')
    if (-not $server.WaitForExit(30000)) {
        throw 'CLI shutdown process timeout'
    }
    Assert-PortClosed
    Assert-NoRuntimeFiles $data
    Write-Report "CLI_EXIT=$($server.ExitCode)"

    $stage = 'backup-restore'
    Write-Report "STAGE=$stage"
    python -c "from backend.db import LibraryDatabase; from pathlib import Path; LibraryDatabase(Path(r'$data')/'library.db').add_or_update_movie('ACCEPT-A')"
    Run-Yav @('--data-dir', $data, '--backup')
    $backup = Get-ChildItem (Join-Path $data 'backups') -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $backup) {
        throw 'Backup directory was not created'
    }
    $manifest = Get-Content (Join-Path $backup.FullName 'manifest.json') -Raw | ConvertFrom-Json
    $runtimeEntries = @($manifest.files | Where-Object { $_.path -like 'runtime/*' })
    if ($runtimeEntries.Count -ne 0) {
        throw 'Backup manifest contains runtime files'
    }
    python -c "from backend.db import LibraryDatabase; from pathlib import Path; LibraryDatabase(Path(r'$data')/'library.db').add_or_update_movie('ACCEPT-B')"
    Run-Yav @('--data-dir', $data, '--restore', $backup.FullName, '--dry-run')
    python ci/verify_rc5_acceptance.py dry-restore (Join-Path $data 'library.db')
    Run-Yav @('--data-dir', $data, '--restore', $backup.FullName)
    python ci/verify_rc5_acceptance.py restored (Join-Path $data 'library.db')
    Write-Report "BACKUP=$($backup.FullName)"

    $stage = 'v1-migration'
    Write-Report "STAGE=$stage"
    $v1 = Join-Path $root 'v1.db'
    python ci/make_v1_fixture.py $v1
    $v1Hash = (Get-FileHash $v1 -Algorithm SHA256).Hash
    Run-Yav @('--data-dir', $migrationData, '--migrate-v1', $v1, '--dry-run')
    if (Test-Path (Join-Path $migrationData 'library.db')) {
        throw 'Migration dry-run created a V2 database'
    }
    Run-Yav @('--data-dir', $migrationData, '--migrate-v1', $v1)
    Run-Yav @('--data-dir', $migrationData, '--migrate-v1', $v1)
    python ci/verify_rc5_acceptance.py migrated (Join-Path $migrationData 'library.db')
    if ((Get-FileHash $v1 -Algorithm SHA256).Hash -ne $v1Hash) {
        throw 'V1 database was modified'
    }

    $stage = 'log-redaction'
    Write-Report "STAGE=$stage"
    $logText = @(
        Get-ChildItem $root -Recurse -Filter '*.log' -File |
            ForEach-Object { Get-Content $_.FullName -Raw }
    ) -join "`n"
    if ($logText -match 'magnet:\?' -or $logText -match '(?i)(cookie|authorization|shutdownToken|token=)') {
        throw 'Sensitive material was found in logs'
    }

    Write-Report 'FINAL_ACCEPTANCE_SUCCESS'
}
catch {
    Write-Report "FINAL_ACCEPTANCE_FAILURE stage=$stage type=$($_.Exception.GetType().FullName) message=$($_.Exception.Message)"
    Add-Content $report ($_ | Format-List * -Force | Out-String)
    $applicationLog = Join-Path $data 'logs\yav.log'
    if (Test-Path $applicationLog) {
        Add-Content $report '--- YAV LOG ---'
        Get-Content $applicationLog | Add-Content $report
    }
    throw
}
finally {
    if ($server -and -not $server.HasExited) {
        $server.Kill($true)
    }
    if ($http -and -not $http.HasExited) {
        Stop-Process -Id $http.Id -Force
    }
}

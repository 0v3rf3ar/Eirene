# Works in Windows PowerShell 5.1 and PowerShell 7 (Windows, macOS, Linux).
[CmdletBinding()]
param(
    [string]$Version = $(if ($env:EIRENE_VERSION) { $env:EIRENE_VERSION } else { 'latest' }),
    [string]$InstallDir = $env:EIRENE_INSTALL_DIR,
    [switch]$NoPathUpdate
)
$ErrorActionPreference = 'Stop'
function Write-Step([int]$Number, [string]$Text) {
    if ($null -eq $env:NO_COLOR) { Write-Host "`n[$Number/7] $Text" -ForegroundColor Cyan }
    else { Write-Host "`n[$Number/7] $Text" }
}
function Write-OK([string]$Text) {
    if ($null -eq $env:NO_COLOR) { Write-Host "[ok] $Text" -ForegroundColor Green }
    else { Write-Host "[ok] $Text" }
}
function Show-Eirene {
    # Embedded artwork needs no image viewer, Python or additional download.
    if (-not [Console]::IsOutputRedirected -and [Console]::WindowWidth -ge 56) {
        $portrait = [regex]::Unescape(@'
                    \u2820\u2824\u28e4\u28c0\u2840
                       \u2819\u283b\u28f7\u28c4
         \u2840              \u28e4\u2808\u283b\u28f7\u2844  \u28b0\u28ff
       \u2820\u280a    \u2840\u2880\u2840\u28e4\u28c4\u28c0\u28e0\u28f6\u28fc\u283f\u2826\u2808 \u2808\u2819\u2819\u2802\u2808\u2819\u2802
       \u2850\u2824\u2830\u2816\u2807\u2810\u281b\u2809\u2801\u2848\u2801\u2809\u2801\u2801
      \u2870         \u28f7\u2840
     \u28b0\u2847    \u28b0\u2840 \u2840\u28b8\u2818\u28fb\u28e4\u28e4\u28c0\u28c0\u28c0\u2880     \u28c0\u28e4\u28c4
     \u2818\u2847\u2846   \u28c8\u28f3\u28e6\u28f5\u287c\u280b\u2801\u2808\u2809\u2889\u28fd\u28ff\u28ff\u28ff\u28e7\u2840\u2880\u28fc\u28c7\u28fb\u28fe\u2806
       \u2839\u28a6\u2840   \u2808\u28ff\u28c7    \u28fc\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u284b\u28c0\u28fc\u280f      \u2820
         \u2808   \u28f4\u28ff\u28ff\u28f7\u28e6\u28f4\u28fe\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u281f\u2801\u280b\u2801   \u2822    \u2886
            \u2818\u28ff\u283f\u283f\u283f\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u28c6\u285f          \u2818\u2844
          \u28fc  \u2808\u28b7\u28fc\u28ff\u28ff\u28ff\u28ff\u28ff\u28ff\u287f\u28ff\u28ff\u28ff\u28ff\u28fe\u2847\u2840  \u28f0\u285c\u2803    \u2820\u28f9\u2844
          \u2809    \u2839\u28ff\u287f\u283f\u281b\u2809\u2881\u28fe\u28ff\u28ff\u28ff\u28ff\u28ff\u28f7\u28c7          \u28b9\u28ff\u2844
        \u28f8  \u2830         \u28ff\u28ff\u28ff\u287f\u28ff\u28ff\u28ff\u28df\u28bf\u2804\u2804         \u283b\u28f7
        \u28bf\u2840\u2844          \u2838\u28ff\u28df\u28fc\u28ff\u28ff\u28ff\u28ff\u2802        \u2880 \u2840\u28a0\u2818
        \u2808\u287d\u2801           \u28b9\u28ff\u28ff\u28bf\u283f\u281f\u2809    \u2880\u28c4   \u2808 \u2801 \u28c7 \u28e7
        \u2808\u2801\u28e0\u2846  \u2820\u2803       \u28ff\u28ff\u28f6\u2846\u2809             \u2820\u2803\u2818\u2803
                   \u2880\u28e4\u2816\u28f7\u28ff\u283f\u280b  \u28e0\u2814\u2809          \u2840
          \u2824\u2804\u2860\u2802     \u28be\u2807\u28fc\u281f\u2801\u2802 \u280a\u2808\u2801
           \u2808\u2801      \u2808 \u2801
'@)
        if ($null -eq $env:NO_COLOR) { Write-Host $portrait -ForegroundColor Cyan }
        else { Write-Host $portrait }
    }
    Write-Host 'E I R E N E  /  terminal coding agent'
}
Write-Host 'E I R E N E  /  installer'
Write-Step 1 'Check this computer'
$repo = '0v3rf3ar/Eirene'
$temporary = $null
$staged = $null
$installed = $false
$phase = 'checking this computer'
try {
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($onWindows) {
    $cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($cpu -ne 'AMD64') { throw "Unsupported Windows architecture: $cpu. The Windows release requires AMD64." }
    $target = 'Windows-amd64'
    $binaryName = 'eirene.exe'
    $extension = 'zip'
    if (-not $InstallDir) {
        $localPrograms = [Environment]::GetFolderPath('LocalApplicationData')
        if (-not $localPrograms) { throw 'Could not locate Local AppData. Set EIRENE_INSTALL_DIR to a writable directory.' }
        $InstallDir = Join-Path $localPrograms 'Programs\eirene'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} else {
    $osName = (& uname -s).Trim()
    $cpu = (& uname -m).Trim()
    switch ($osName) {
        'Linux' {
            switch ($cpu) {
                { $_ -in 'x86_64', 'amd64' } { $target = 'Linux-amd64'; break }
                { $_ -in 'aarch64', 'arm64' } { $target = 'Linux-arm64'; break }
                default { throw "Unsupported Linux architecture: $cpu" }
            }
        }
        'Darwin' {
            if ($cpu -notin 'arm64', 'aarch64') {
                $silicon = & sysctl -n hw.optional.arm64 2>$null
                if ($silicon -ne '1') { throw 'The macOS release requires Apple Silicon.' }
            }
            $target = 'MacOS-silicon'
        }
        default { throw "Unsupported operating system: $osName" }
    }
    $binaryName = 'eirene'
    $extension = 'tar.gz'
    if (-not $InstallDir) { $InstallDir = Join-Path $HOME '.local/bin' }
}
if ($InstallDir.IndexOfAny(@([char]10, [char]13, [IO.Path]::PathSeparator)) -ge 0) {
    throw 'Install directory must not contain newlines or the PATH separator.'
}

function Open-ReleaseDownload([string]$Uri) {
    $request = [Net.WebRequest]::Create($Uri)
    $request.Timeout = 15000
    $request.ReadWriteTimeout = 300000
    $request.UserAgent = 'Eirene-installer'
    $response = $request.GetResponse()
    if ($response.ResponseUri.Scheme -ne 'https') {
        $response.Close()
        throw 'Release download redirected away from HTTPS.'
    }
    return [pscustomobject]@{ Stream = $response.GetResponseStream(); Length = $response.ContentLength; Response = $response }
}

function Install-StagedExecutable([string]$Source, [string]$Destination) {
    # PyInstaller cleanup and antivirus scans can briefly retain a handle after
    # --version/--help return. Retry sharing/lock violations for at most 5 seconds;
    # permission failures and other errors remain immediate failures.
    for ($attempt = 0; $attempt -lt 26; $attempt++) {
        try {
            if (Test-Path -LiteralPath $Destination) {
                [IO.File]::Replace($Source, $Destination, [NullString]::Value)
            } else {
                [IO.File]::Move($Source, $Destination)
            }
            return
        } catch {
            $cause = $_.Exception
            while ($cause.InnerException) { $cause = $cause.InnerException }
            $code = $cause.HResult -band 0xffff
            if (-not $onWindows -or -not ($cause -is [IO.IOException]) -or
                $code -notin @(32, 33) -or $attempt -eq 25) { throw }
            if ($attempt -eq 0) { Write-Host 'Executable is briefly locked; waiting up to 5 seconds before retrying...' }
            Start-Sleep -Milliseconds 200
        }
    }
}

function Get-ReleaseFile([string]$Uri, [string]$Destination, [switch]$ShowProgress) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $download = $null
        $output = $null
        try {
            if (-not $ShowProgress) {
                Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 300
            } else {
                $download = Open-ReleaseDownload $Uri
                $output = [IO.File]::Create($Destination)
                $buffer = New-Object byte[] 65536
                $received = [long]0
                $timer = [Diagnostics.Stopwatch]::StartNew()
                $lastUpdate = -1.0
                while (($count = $download.Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $count)
                    $received += $count
                    $elapsed = $timer.Elapsed.TotalSeconds
                    if ($elapsed -gt 300) { throw 'Download exceeded five minutes.' }
                    if ($elapsed - $lastUpdate -lt 0.12) { continue }
                    $lastUpdate = $elapsed
                    $speed = $received / [Math]::Max($elapsed, 0.001)
                    if ($download.Length -gt 0) {
                        $percent = [Math]::Min(100, [int](100 * $received / $download.Length))
                        $filled = [int]($percent / 5)
                        $bar = '[' + ('=' * $filled) + (' ' * (20 - $filled)) + ']'
                        $status = '{0} {1}% | {2:N1} / {3:N1} MiB | {4:N1} MiB/s' -f $bar, $percent, ($received / 1MB), ($download.Length / 1MB), ($speed / 1MB)
                        $eta = [int][Math]::Min(2147483647, [Math]::Max(0, ($download.Length - $received) / $speed))
                        Write-Progress -Id 1 -Activity 'Downloading Eirene' -Status $status -PercentComplete $percent -SecondsRemaining $eta
                    } else {
                        Write-Progress -Id 1 -Activity 'Downloading Eirene' -Status ('{0:N1} MiB | {1:N1} MiB/s' -f ($received / 1MB), ($speed / 1MB))
                    }
                }
                if ($received -eq 0) { throw 'Downloaded archive is empty.' }
                if ($download.Length -ge 0 -and $received -ne $download.Length) { throw 'Archive download was incomplete.' }
                Write-OK ('Downloaded {0:N1} MiB' -f ($received / 1MB))
            }
            return
        } catch {
            if ($attempt -eq 4) { throw "Could not download $Uri after 4 attempts. Check your connection and release availability. $($_.Exception.Message)" }
            Write-Host "Download interrupted; retrying ($attempt/3)..."
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        } finally {
            if ($output) { $output.Dispose() }
            if ($download) {
                $download.Stream.Dispose()
                if ($download.Response) { $download.Response.Close() }
            }
            if ($ShowProgress) { Write-Progress -Id 1 -Activity 'Downloading Eirene' -Completed }
        }
    }
}
Write-OK "$target / $InstallDir"
Write-Step 2 'Find the release'

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('eirene-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    if ($Version -eq 'latest') {
        $phase = 'finding the latest release'
        $metadata = Join-Path $temporary 'release.json'
        Get-ReleaseFile "https://api.github.com/repos/$repo/releases/latest" $metadata
        $Version = (Get-Content -Raw -LiteralPath $metadata | ConvertFrom-Json).tag_name
    }
    if ($Version -cnotmatch '^v[0-9][A-Za-z0-9._+-]*$') { throw "Invalid release tag: $Version" }
    $asset = "eirene-$target-$($Version.Substring(1)).$extension"
    $base = "https://github.com/$repo/releases/download/$Version"
    $archive = Join-Path $temporary $asset
    $checksums = Join-Path $temporary 'SHA256SUMS'
    Write-OK "Release $Version"
    Write-Step 3 'Download'
    Show-Eirene
    Write-Host "Eirene $Version for $target"
    $phase = 'downloading the release and checksums'
    Get-ReleaseFile "$base/$asset" $archive -ShowProgress
    Get-ReleaseFile "$base/SHA256SUMS" $checksums
    Write-Step 4 'Verify and unpack'
    $phase = 'verifying the downloaded archive'
    $pattern = '^([0-9a-fA-F]{64})  ' + [regex]::Escape($asset) + '$'
    $hashes = @(foreach ($line in (Get-Content -LiteralPath $checksums)) {
        if ($line -match $pattern) { $Matches[1] }
    })
    if ($hashes.Count -ne 1) { throw "Missing or invalid checksum for $asset" }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $hashes[0]) {
        throw 'Checksum mismatch; existing installation was not changed.'
    }
    Write-OK 'SHA-256 checksum matches'
    $phase = 'extracting the release archive'
    if ($onWindows) {
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $temporary 'unpacked')
        $source = Join-Path $temporary "unpacked\$binaryName"
    } else {
        & tar -xzf $archive -C $temporary eirene
        if ($LASTEXITCODE -ne 0) { throw 'Could not extract release archive.' }
        $source = Join-Path $temporary $binaryName
    }
    $item = Get-Item -LiteralPath $source
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Archive must contain a regular executable.'
    }
    Write-OK 'Executable extracted'
    Write-Step 5 'Install the executable'
    $phase = "preparing $InstallDir; check directory permissions and free disk space"
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $InstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
    $destination = Join-Path $InstallDir $binaryName
    $staged = Join-Path $InstallDir ('.eirene-' + [guid]::NewGuid().ToString('N') + $(if ($onWindows) { '.exe' } else { '' }))
    Copy-Item -LiteralPath $source -Destination $staged
    if (-not $onWindows) {
        & chmod 755 $staged
        if ($LASTEXITCODE -ne 0) { throw 'Could not make the binary executable.' }
    }
    $phase = 'checking the executable; check OS compatibility and execution permissions'
    $binaryVersion = & $staged --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Downloaded binary could not run; existing installation was not changed.' }
    $binaryHelp = & $staged --help 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $binaryVersion -or -not $binaryHelp) { throw 'Downloaded binary failed version/help checks; existing installation was not changed.' }
    Write-OK 'Staged executable responds to --version and --help'
    if (Test-Path -LiteralPath $destination -PathType Container) { throw "$destination is a directory." }
    $phase = "replacing $destination; close any running Eirene window and retry if the executable is locked"
    Install-StagedExecutable $staged $destination
    $staged = $null
    $installed = $true
    Write-OK "Installed $destination"
    Write-Step 6 'Configure installed shells'
    $pathReady = $false
    if (-not $NoPathUpdate -and $env:EIRENE_NO_PATH -ne '1') {
        Write-Host 'Configuring PATH...'
        try {
            if ($onWindows) {
                $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
                $parts = @($userPath -split ';' | Where-Object { $_ })
                $remaining = @($parts | Where-Object {
                    [Environment]::ExpandEnvironmentVariables($_.Trim().Trim('"')).TrimEnd('\') -ine $InstallDir.TrimEnd('\')
                })
                $newPath = (@($InstallDir) + $remaining) -join ';'
                if ($newPath -cne $userPath) {
                    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
                }
                Write-Host 'Saved to your user PATH (no administrator access needed).'
            } else {
                # A PowerShell install persists in PowerShell's own startup file.
                $profileFile = $PROFILE.CurrentUserAllHosts
                $quotedDir = "'" + $InstallDir.Replace("'", "''") + "'"
                $pathLine = 'if (($env:PATH -split [IO.Path]::PathSeparator) -cnotcontains ' + $quotedDir + ') { $env:PATH = ' + $quotedDir + ' + [IO.Path]::PathSeparator + $env:PATH }'
                $existing = if (Test-Path -LiteralPath $profileFile) { [IO.File]::ReadAllText($profileFile) } else { '' }
                if (($existing -split '\r?\n') -cnotcontains $pathLine) {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $profileFile) -Force | Out-Null
                    if (Test-Path -LiteralPath $profileFile) {
                        $backup = $profileFile + '.eirene-backup.' + [guid]::NewGuid().ToString('N')
                        Copy-Item -LiteralPath $profileFile -Destination $backup
                        Write-Host "Profile backup: $backup"
                    }
                    [IO.File]::AppendAllText($profileFile, "`n# Eirene`n$pathLine`n", [Text.UTF8Encoding]::new($false))
                }
                Write-Host "PATH configured in $profileFile"
                if (Get-Command bash -ErrorAction SilentlyContinue) {
                    $phase = 'configuring installed Unix shells'
                    $shellInstaller = Join-Path $temporary 'install.sh'
                    Get-ReleaseFile "$base/install.sh" $shellInstaller
                    $installerPattern = '^([0-9a-fA-F]{64})  install\.sh$'
                    $installerHashes = @(foreach ($line in (Get-Content -LiteralPath $checksums)) {
                        if ($line -match $installerPattern) { $Matches[1] }
                    })
                    if ($installerHashes.Count -ne 1 -or (Get-FileHash -LiteralPath $shellInstaller -Algorithm SHA256).Hash -ne $installerHashes[0]) {
                        throw 'Shell installer checksum mismatch.'
                    }
                    if (-not ([IO.File]::ReadAllText($shellInstaller).Contains('--configure-shells'))) {
                        throw 'This release predates automatic Unix shell setup. Use install.sh directly or configure other shells manually.'
                    }
                    $savedInstallDir = $env:EIRENE_INSTALL_DIR
                    try {
                        $env:EIRENE_INSTALL_DIR = $InstallDir
                        & bash $shellInstaller --configure-shells
                        if ($LASTEXITCODE -ne 0) { throw 'Unix shell configuration failed.' }
                    } finally { $env:EIRENE_INSTALL_DIR = $savedInstallDir }
                } else {
                    throw 'Bash is unavailable; Unix shell profiles could not be configured. PowerShell PATH is saved.'
                }
            }
            $pathReady = $true
        } catch {
            Write-Warning "Eirene is installed, but persistent PATH setup failed: $($_.Exception.Message) Use the full launch command below; fix permissions and rerun to finish PATH setup."
        }
        $currentParts = @($env:PATH -split [IO.Path]::PathSeparator | Where-Object {
            if ($onWindows) { $_ -ine $InstallDir } else { $_ -cne $InstallDir }
        })
        $env:PATH = (@($InstallDir) + $currentParts) -join [IO.Path]::PathSeparator
    } else {
        Write-Host 'PATH setup skipped.'
    }
    Write-Step 7 'Check the installed command'
    $phase = 'verifying the installed command'
    if (-not $NoPathUpdate -and $env:EIRENE_NO_PATH -ne '1') {
        $resolvedCommand = @(Get-Command eirene -CommandType Application -ErrorAction Stop)[0]
        if ($resolvedCommand.Source -ne $destination) { throw "PATH resolves to another Eirene: $($resolvedCommand.Source)" }
        $installedVersion = & $resolvedCommand.Source --version 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $installedVersion) { throw 'Eirene could not run through PATH.' }
        $installedVersion | Out-Host
        Write-OK 'eirene resolves on PATH and runs'
    } else {
        $installedVersion = & $destination --version 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $installedVersion) { throw 'Installed executable failed --version.' }
        Write-OK 'Installed command runs'
    }
    Write-Host "`nEirene $Version installed`n$destination`n"
    $launch = "& '" + $destination.Replace("'", "''") + "'"
    Write-Host "Start now:`n$launch`n"
    if ($pathReady) {
        Write-Host 'Run eirene in this PowerShell window, or open a new terminal and run: eirene'
        if ($onWindows) { Write-Host 'If an existing terminal app has an old PATH, close all its windows and reopen it.' }
    }
    Write-Host "`nInside Eirene, use /connect to choose a provider and /help for commands."
} catch {
    $preserved = if ($installed) { 'The executable was installed; see the error for the unfinished step.' } else { 'The existing executable has not been replaced.' }
    throw "Installation failed while $phase. $($_.Exception.Message) $preserved"
} finally {
    foreach ($leftover in @($staged, $temporary)) {
        if ($leftover -and (Test-Path -LiteralPath $leftover)) {
            try { Remove-Item -LiteralPath $leftover -Recurse -Force }
            catch { Write-Warning "Could not remove temporary files at ${leftover}: $($_.Exception.Message)" }
        }
    }
}

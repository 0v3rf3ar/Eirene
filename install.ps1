# Works in Windows PowerShell 5.1 and PowerShell 7 (Windows, macOS, Linux).
[CmdletBinding()]
param(
    [string]$Version = $(if ($env:EIRENE_VERSION) { $env:EIRENE_VERSION } else { 'latest' }),
    [string]$InstallDir = $env:EIRENE_INSTALL_DIR,
    [switch]$NoPathUpdate
)
$ErrorActionPreference = 'Stop'
# Unicode escapes keep the banner compatible with Windows PowerShell 5.1 file decoding.
Write-Host ([regex]::Unescape('\n\u250f\u2501\u2578\u257b\u250f\u2501\u2513\u250f\u2501\u2578\u250f\u2513\u257b\u250f\u2501\u2578\n\u2523\u2578 \u2503\u2523\u2533\u251b\u2523\u2578 \u2503\u2517\u252b\u2523\u2578\n\u2517\u2501\u2578\u2579\u2579\u2517\u2578\u2517\u2501\u2578\u2579 \u2579\u2517\u2501\u2578\n'))
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

function Get-ReleaseFile([string]$Uri, [string]$Destination) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 300
            return
        } catch {
            if ($attempt -eq 4) { throw "Could not download $Uri after 4 attempts. Check your connection and release availability. $($_.Exception.Message)" }
            Write-Host "  Download interrupted; retrying ($attempt/3)..."
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
}

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
    Write-Host "Downloading Eirene $Version for $target..."
    $phase = 'downloading the release and checksums'
    Get-ReleaseFile "$base/$asset" $archive
    Get-ReleaseFile "$base/SHA256SUMS" $checksums
    Write-Host 'Verifying download...'
    $phase = 'verifying the downloaded archive'
    $pattern = '^([0-9a-fA-F]{64})  ' + [regex]::Escape($asset) + '$'
    $hashes = @(foreach ($line in (Get-Content -LiteralPath $checksums)) {
        if ($line -match $pattern) { $Matches[1] }
    })
    if ($hashes.Count -ne 1) { throw "Missing or invalid checksum for $asset" }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $hashes[0]) {
        throw 'Checksum mismatch; existing installation was not changed.'
    }
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
    if (Test-Path -LiteralPath $destination -PathType Container) { throw "$destination is a directory." }
    $phase = "replacing $destination; close any running Eirene window and retry if the executable is locked"
    if (Test-Path -LiteralPath $destination) {
        [IO.File]::Replace($staged, $destination, [NullString]::Value)
    } else {
        [IO.File]::Move($staged, $destination)
    }
    $staged = $null
    $installed = $true
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
                Write-Host '  Saved to your user PATH (no administrator access needed).'
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
                        Write-Host "  Profile backup: $backup"
                    }
                    [IO.File]::AppendAllText($profileFile, "`n# Eirene`n$pathLine`n", [Text.UTF8Encoding]::new($false))
                }
                Write-Host "  PATH configured in $profileFile"
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
    Write-Host "`nEirene $Version installed`n  $destination`n"
    $launch = "& '" + $destination.Replace("'", "''") + "'"
    Write-Host "Start now:`n  $launch`n"
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

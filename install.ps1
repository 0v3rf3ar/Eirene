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
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($onWindows) {
    $cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($cpu -ne 'AMD64') { throw "Unsupported Windows architecture: $cpu. The Windows release requires AMD64." }
    $target = 'Windows-amd64'
    $binaryName = 'eirene.exe'
    $extension = 'zip'
    if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Eirene\bin' }
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

function Get-ReleaseFile([string]$Uri, [string]$Destination) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 300
            return
        } catch {
            if ($attempt -eq 4) { throw }
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('eirene-install-' + [guid]::NewGuid().ToString('N'))
$staged = $null
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    if ($Version -eq 'latest') {
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
    Get-ReleaseFile "$base/$asset" $archive
    Get-ReleaseFile "$base/SHA256SUMS" $checksums
    $pattern = '^([0-9a-fA-F]{64})  ' + [regex]::Escape($asset) + '$'
    $hashes = @(foreach ($line in (Get-Content -LiteralPath $checksums)) {
        if ($line -match $pattern) { $Matches[1] }
    })
    if ($hashes.Count -ne 1) { throw "Missing or invalid checksum for $asset" }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $hashes[0]) {
        throw 'Checksum mismatch; existing installation was not changed.'
    }
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
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $InstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
    $destination = Join-Path $InstallDir $binaryName
    $staged = Join-Path $InstallDir ('.eirene-' + [guid]::NewGuid().ToString('N') + $(if ($onWindows) { '.exe' } else { '' }))
    Copy-Item -LiteralPath $source -Destination $staged
    if (-not $onWindows) {
        & chmod 755 $staged
        if ($LASTEXITCODE -ne 0) { throw 'Could not make the binary executable.' }
    }
    & $staged --version
    if ($LASTEXITCODE -ne 0) { throw 'Downloaded binary could not run; existing installation was not changed.' }
    if (Test-Path -LiteralPath $destination -PathType Container) { throw "$destination is a directory." }
    if (Test-Path -LiteralPath $destination) {
        [IO.File]::Replace($staged, $destination, [NullString]::Value)
    } else {
        [IO.File]::Move($staged, $destination)
    }
    $staged = $null
    if (-not $NoPathUpdate -and $env:EIRENE_NO_PATH -ne '1') {
        if ($onWindows) {
            $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
            $parts = @($userPath -split ';' | Where-Object { $_ })
            if ($parts -notcontains $InstallDir) {
                [Environment]::SetEnvironmentVariable('Path', (($parts + $InstallDir) -join ';'), 'User')
            }
        }
        if (($env:PATH -split [IO.Path]::PathSeparator) -notcontains $InstallDir) {
            $env:PATH = $InstallDir + [IO.Path]::PathSeparator + $env:PATH
        }
        if (-not $onWindows) {
            Write-Host "For future terminals, add $InstallDir to PATH in your shell profile."
        }
    }
    Write-Host "Installed to $destination. Run eirene to get started."
} finally {
    if ($staged -and (Test-Path -LiteralPath $staged)) { Remove-Item -LiteralPath $staged -Force }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}

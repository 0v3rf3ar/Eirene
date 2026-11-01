# Works in Windows PowerShell 5.1 and PowerShell 7 (Windows, macOS, Linux).
# Non-ASCII output is built from code points: Windows PowerShell 5.1 reads a
# script file without a byte-order mark in the legacy code page.
[CmdletBinding()]
param(
    [string]$Version = $(if ($env:EIRENE_VERSION) { $env:EIRENE_VERSION } else { 'latest' }),
    [string]$InstallDir = $env:EIRENE_INSTALL_DIR,
    [switch]$NoPathUpdate,
    [switch]$Edge
)
$ErrorActionPreference = 'Stop'

# A VT console gets colour, the portrait and a live bar; logs get plain lines.
$fancy = (-not [Console]::IsOutputRedirected) -and ($null -eq $env:NO_COLOR) -and
    [bool]$Host.UI.SupportsVirtualTerminal
$esc = [char]27
$savedOutputEncoding = $null
if ($fancy) {
    $savedOutputEncoding = [Console]::OutputEncoding
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
    $reset = "$esc[0m"; $bold = "$esc[1m"; $dim = "$esc[2m"
    $green = "$esc[38;2;120;220;150m"; $cyan = "$esc[38;2;90;200;255m"
    $violet = "$esc[38;2;190;130;255m"; $yellow = "$esc[38;2;240;200;110m"
    $pad = '  '
} else {
    $reset = ''; $bold = ''; $dim = ''; $green = ''; $cyan = ''; $violet = ''; $yellow = ''; $pad = ''
}
$checkMark = [string][char]0x2713
$middleDot = [string][char]0x00B7
$spinnerFrame = [string][char]0x280B
$fullBlock = [string][char]0x2588
$trackLine = [string][char]0x2500
$eighths = @('', [string][char]0x258F, [string][char]0x258E, [string][char]0x258D,
    [string][char]0x258C, [string][char]0x258B, [string][char]0x258A, [string][char]0x2589)
$pendingLine = $false

function Write-Raw([string]$Text) { [Console]::Write($Text) }
function Clear-Pending {
    if ($script:pendingLine) { Write-Raw "`r$esc[2K"; $script:pendingLine = $false }
}
function Start-Line([string]$Text) {
    if (-not $fancy) { return }
    Write-Raw "  $cyan$spinnerFrame$reset $dim$Text$reset"
    $script:pendingLine = $true
}
function Write-Done([string]$Text) {
    Clear-Pending
    if ($fancy) { Write-Raw "  $green$checkMark$reset $Text`n" } else { Write-Host "[ok] $Text" }
}
function Write-Note([string]$Text) {
    Clear-Pending
    if ($fancy) { Write-Raw "  $dim$middleDot $Text$reset`n" } else { Write-Host $Text }
}
function Write-Caution([string]$Text) {
    Clear-Pending
    if ($fancy) { Write-Raw "  $yellow!$reset $Text`n" } else { Write-Warning $Text }
}
function Format-Path([string]$Path) {
    $homeDirectory = if ($onWindows) { $env:USERPROFILE } else { $HOME }
    if ($homeDirectory -and $Path.StartsWith($homeDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        return '~' + $Path.Substring($homeDirectory.Length)
    }
    return $Path
}
function Show-Eirene {
    if (-not $fancy -or [Console]::WindowWidth -lt 56) { return }
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
    $rows = $portrait -split "`n"
    $count = $rows.Count
    Write-Raw "`n"
    for ($index = 0; $index -lt $count; $index++) {
        $red = 90 + [int](100 * $index / ($count - 1))
        $greenValue = 200 - [int](70 * $index / ($count - 1))
        Write-Raw "$esc[38;2;$red;$greenValue;255m$($rows[$index].TrimEnd("`r"))$reset`n"
    }
}

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
    $systemLabel = "Windows $middleDot x64"
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
    $systemLabel = "$($osName.Replace('Darwin', 'macOS')) $middleDot $cpu"
    $binaryName = 'eirene'
    $extension = 'tar.gz'
    if (-not $InstallDir) { $InstallDir = Join-Path $HOME '.local/bin' }
}
if ($InstallDir.IndexOfAny(@([char]10, [char]13, [IO.Path]::PathSeparator)) -ge 0) {
    throw 'Install directory must not contain newlines or the PATH separator.'
}

function Open-ReleaseDownload([string]$Uri) {
    $request = [Net.WebRequest]::Create($Uri)
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 600000
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
    # --version/--help return. Retry sharing/lock violations for at most 10 seconds;
    # permission failures and other errors remain immediate failures.
    for ($attempt = 0; $attempt -lt 51; $attempt++) {
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
                $code -notin @(32, 33) -or $attempt -eq 50) { throw }
            if ($attempt -eq 0) { Write-Note 'Executable is briefly locked; retrying for up to 10 seconds' }
            Start-Sleep -Milliseconds 200
        }
    }
}

function Write-DownloadBar([long]$Received, [long]$Length, [double]$Speed) {
    $width = 28
    $megabytes = '{0:N1}' -f ($Received / 1MB)
    if ($Length -le 0) {
        Write-Raw ("`r$esc[2K    $violet$spinnerFrame$reset $megabytes MB")
        return
    }
    $fill = [int][Math]::Floor($Received * $width * 8 / $Length)
    $full = [int][Math]::Floor($fill / 8)
    $part = $fill % 8
    $bar = ($fullBlock * $full) + $eighths[$part]
    $track = $trackLine * [Math]::Max(0, $width - $full - $(if ($part -gt 0) { 1 } else { 0 }))
    $percent = [Math]::Min(100, [int][Math]::Floor(100 * $Received / $Length))
    $status = '{0,3}%  {1} / {2:N1} MB' -f $percent, $megabytes, ($Length / 1MB)
    if ($Speed -gt 0) {
        $status += '  {0:N1} MB/s  {1}s left' -f ($Speed / 1MB), [int][Math]::Max(0, ($Length - $Received) / $Speed)
    }
    Write-Raw ("`r$esc[2K    $violet$bar$reset$dim$track $status$reset")
}

function Get-ReleaseFile([string]$Uri, [string]$Destination, [switch]$ShowProgress) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $download = $null
        $output = $null
        $drawing = $false
        try {
            if (-not $ShowProgress) {
                Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 600
            } else {
                $download = Open-ReleaseDownload $Uri
                $output = [IO.File]::Create($Destination)
                $buffer = New-Object byte[] 65536
                $received = [long]0
                $timer = [Diagnostics.Stopwatch]::StartNew()
                $lastUpdate = -1.0
                if ($fancy) {
                    Clear-Pending
                    Write-Raw ("$esc[?25l  $cyan" + [char]0x2193 + "$reset $dim$(Split-Path -Leaf $Destination)$reset`n")
                    $drawing = $true
                }
                while (($count = $download.Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $count)
                    $received += $count
                    $elapsed = $timer.Elapsed.TotalSeconds
                    if ($elapsed -gt 600) { throw 'Download exceeded ten minutes.' }
                    if (-not $drawing -or $elapsed - $lastUpdate -lt 0.1) { continue }
                    $lastUpdate = $elapsed
                    Write-DownloadBar $received $download.Length ($received / [Math]::Max($elapsed, 0.001))
                }
                if ($received -eq 0) { throw 'Downloaded archive is empty.' }
                if ($download.Length -ge 0 -and $received -ne $download.Length) { throw 'Archive download was incomplete.' }
                if ($drawing) { Write-Raw "`r$esc[2K$esc[1A$esc[2K"; $drawing = $false }
                Write-Done ("Downloaded $(Split-Path -Leaf $Destination) $dim({0:N1} MB)$reset" -f ($received / 1MB))
            }
            return
        } catch {
            if ($drawing) { Write-Raw "`r$esc[2K$esc[1A$esc[2K" }
            if ($attempt -eq 4) { throw "Could not download $Uri after 4 attempts. Check your connection and release availability. $($_.Exception.Message)" }
            Write-Note "Download interrupted; retrying ($attempt/3)"
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        } finally {
            if ($fancy -and $ShowProgress) { Write-Raw "$esc[?25h" }
            if ($output) { $output.Dispose() }
            if ($download) {
                $download.Stream.Dispose()
                if ($download.Response) { $download.Response.Close() }
            }
        }
    }
}

    Show-Eirene
    if ($fancy) {
        Write-Raw "`n  $bold${cyan}E I R E N E$reset  $dim$middleDot  terminal coding agent$reset`n`n"
    } else {
        Write-Host 'Eirene installer'
    }
    Write-Done $systemLabel
    Start-Line 'Finding the release'
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('eirene-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    if ($Edge -or $Version -eq 'edge') {
        $phase = 'finding the latest unstable release'
        $metadata = Join-Path $temporary 'releases.json'
        $candidate = $null
        $page = 1
        do {
            Get-ReleaseFile "https://api.github.com/repos/$repo/releases?per_page=100&page=$page" $metadata
            # Windows PowerShell 5.1 returns a JSON array as one object; enumerate it.
            $parsed = Get-Content -Raw -LiteralPath $metadata | ConvertFrom-Json
            $releases = @(foreach ($entry in $parsed) { $entry })
            foreach ($release in $releases) {
                if ($release.prerelease -eq $true -and $release.draft -eq $false -and
                    (-not $candidate -or $release.published_at -gt $candidate.published_at)) {
                    $candidate = $release
                }
            }
            $page++
        } while ($releases.Count -eq 100)
        if (-not $candidate) { throw 'No published unstable release is available.' }
        $Version = $candidate.tag_name
    } elseif ($Version -eq 'latest') {
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
    Write-Done "Eirene $Version"
    $phase = 'downloading the release and checksums'
    Get-ReleaseFile "$base/$asset" $archive -ShowProgress
    Start-Line 'Verifying'
    Get-ReleaseFile "$base/SHA256SUMS" $checksums
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
    $binaryHelp = & $staged --help 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $binaryVersion -or -not $binaryHelp) { throw 'Downloaded binary failed version/help checks; existing installation was not changed.' }
    Write-Done 'SHA-256 verified'
    if (Test-Path -LiteralPath $destination -PathType Container) { throw "$destination is a directory." }
    if ($onWindows) {
        $phase = 'waiting for Eirene to close'
        $fullDestination = [IO.Path]::GetFullPath($destination)
        $running = @(Get-Process -Name eirene -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and [IO.Path]::GetFullPath($_.Path) -ieq $fullDestination
        })
        if ($running.Count -gt 0) {
            if ($fancy) { Start-Line 'Waiting for Eirene to close (press Ctrl+D in Eirene)' }
            else { Write-Host "Eirene is running from $destination. Exit it (Ctrl+D) to finish the update; waiting..." }
            $running | Wait-Process -Timeout 1800 -ErrorAction SilentlyContinue
            if (@($running | Where-Object { -not $_.HasExited }).Count -gt 0) {
                throw 'Eirene is still running after 30 minutes; the existing installation was not changed. Exit Eirene and run the command again.'
            }
            Write-Done 'Eirene closed'
        }
    }
    $phase = "replacing $destination; close any running Eirene window and retry if the executable is locked"
    Install-StagedExecutable $staged $destination
    $staged = $null
    $installed = $true
    Write-Done "Installed $(Format-Path $destination)"
    $pathReady = $false
    if (-not $NoPathUpdate -and $env:EIRENE_NO_PATH -ne '1') {
        $phase = 'adding Eirene to PATH'
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
                    Write-Done 'Added to your user PATH'
                } else {
                    Write-Done 'PATH already set'
                }
            } else {
                $profileFile = $PROFILE.CurrentUserAllHosts
                $quotedDir = "'" + $InstallDir.Replace("'", "''") + "'"
                $pathLine = 'if (($env:PATH -split [IO.Path]::PathSeparator) -cnotcontains ' + $quotedDir + ') { $env:PATH = ' + $quotedDir + ' + [IO.Path]::PathSeparator + $env:PATH }'
                $existing = if (Test-Path -LiteralPath $profileFile) { [IO.File]::ReadAllText($profileFile) } else { '' }
                if (($existing -split '\r?\n') -cnotcontains $pathLine) {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $profileFile) -Force | Out-Null
                    if (Test-Path -LiteralPath $profileFile) {
                        $backup = $profileFile + '.eirene-backup.' + [guid]::NewGuid().ToString('N')
                        Copy-Item -LiteralPath $profileFile -Destination $backup
                    }
                    [IO.File]::AppendAllText($profileFile, "`n# Eirene`n$pathLine`n", [Text.UTF8Encoding]::new($false))
                    Write-Done "PATH set in $(Format-Path $profileFile)"
                } else {
                    Write-Done 'PATH already set for PowerShell'
                }
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
            Write-Caution "Eirene is installed, but PATH setup failed: $($_.Exception.Message) Fix it and rerun the installer."
        }
        $currentParts = @($env:PATH -split [IO.Path]::PathSeparator | Where-Object {
            if ($onWindows) { $_ -ine $InstallDir } else { $_ -cne $InstallDir }
        })
        $env:PATH = (@($InstallDir) + $currentParts) -join [IO.Path]::PathSeparator
    } elseif ($env:EIRENE_NO_PATH -eq '1') {
        Write-Note 'PATH setup skipped (EIRENE_NO_PATH=1)'
    }
    $phase = 'verifying the installed command'
    if (-not $NoPathUpdate -and $env:EIRENE_NO_PATH -ne '1') {
        $resolvedCommand = @(Get-Command eirene -CommandType Application -ErrorAction Stop)[0]
        if ($resolvedCommand.Source -ne $destination) { throw "PATH resolves to another Eirene: $($resolvedCommand.Source)" }
        $installedVersion = & $resolvedCommand.Source --version 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $installedVersion) { throw 'Eirene could not run through PATH.' }
    } else {
        $installedVersion = & $destination --version 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $installedVersion) { throw 'Installed executable failed --version.' }
    }
    $installedVersion = "$(@($installedVersion)[0])".Trim()
    $onPath = @(Get-Command eirene -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -eq $destination }).Count -gt 0
    if ($fancy) { Write-Raw "`n$pad$bold$green$installedVersion is installed.$reset`n" }
    else { Write-Host "`n$installedVersion is installed." }
    if ($onPath) { $hint = "Run: ${bold}eirene$reset" }
    else { $hint = "Run it with: & '" + $destination.Replace("'", "''") + "'" }
    if ($fancy) { Write-Raw "$pad$hint`n`n" } else { Write-Host "$hint`n" }
} catch {
    Clear-Pending
    $preserved = if ($installed) { 'The executable was installed; see the error for the unfinished step.' } else { 'The existing executable has not been replaced.' }
    throw "Installation failed while $phase. $($_.Exception.Message) $preserved"
} finally {
    if ($fancy) { [Console]::Write("$esc[?25h") }
    if ($savedOutputEncoding) { [Console]::OutputEncoding = $savedOutputEncoding }
    foreach ($leftover in @($staged, $temporary)) {
        if ($leftover -and (Test-Path -LiteralPath $leftover)) {
            try { Remove-Item -LiteralPath $leftover -Recurse -Force }
            catch { Write-Warning "Could not remove temporary files at ${leftover}: $($_.Exception.Message)" }
        }
    }
}

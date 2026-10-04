# Exercise the real installer against the locally built native release archive.
param([Parameter(Mandatory = $true)][string]$Target)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$extension = if ($Target -eq 'windows-amd64') { 'zip' } else { 'tar.gz' }
# Use fixture-specific names: the mock also sees variables from install.ps1.
$fixtureVersion = (& python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read release version.' }
$label = @{'linux-amd64' = 'Linux-amd64'; 'linux-arm64' = 'Linux-arm64'; 'macos-silicon' = 'MacOS-silicon'; 'windows-amd64' = 'Windows-amd64'}[$Target]
$fixtureAsset = "eirene-$label-$fixtureVersion.$extension"
$archiveFixture = Join-Path $root "release/$fixtureAsset"
$checksumFixture = (Get-FileHash -LiteralPath $archiveFixture -Algorithm SHA256).Hash.ToLowerInvariant()
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('eirene-installer-test-' + [guid]::NewGuid().ToString('N'))
$installDirectory = Join-Path $testRoot 'path with spaces'
$requests = [Collections.Generic.List[string]]::new()
$corrupt = $false
$downloadMode = 'normal'
$downloadAttempts = 0
$retryDelays = [Collections.Generic.List[double]]::new()
function Start-Sleep([double]$Seconds, [int]$Milliseconds) {
    if ($Milliseconds) {
        # Replacement retries need real time for native executable cleanup.
        [Threading.Thread]::Sleep($Milliseconds)
    } else { $retryDelays.Add($Seconds) }
}
$savedProcessPath = $env:PATH
$savedUserPath = if ($Target -eq 'windows-amd64') { [Environment]::GetEnvironmentVariable('Path', 'User') } else { $null }
$savedProfile = $PROFILE
$savedNoPath = $env:EIRENE_NO_PATH
$savedHomeEnv = $env:HOME
$savedConfigHome = $env:XDG_CONFIG_HOME
$savedZdotdir = $env:ZDOTDIR
$savedShell = $env:SHELL
if ($Target -ne 'windows-amd64') {
    $env:HOME = Join-Path $testRoot 'home'
    $env:XDG_CONFIG_HOME = Join-Path $testRoot 'config'
    $env:ZDOTDIR = $env:HOME
    $env:SHELL = '/bin/bash'
    New-Item -ItemType Directory -Path $env:HOME -Force | Out-Null
}
# Substitute only the transport; exercise the real streaming/progress loop.
$installerSource = [IO.File]::ReadAllText((Join-Path $root 'install.ps1'))
$installerSource = $installerSource.Replace('$request = [Net.WebRequest]::Create($Uri)', 'return Open-FixtureDownload $Uri')
$installerSource = $installerSource.Replace('[IO.File]::Replace($Source, $Destination, [NullString]::Value)', 'Invoke-FixtureReplace $Source $Destination')
$installer = [scriptblock]::Create($installerSource)
$replaceMode = 'normal'
$replaceAttempts = 0
function Invoke-FixtureReplace([string]$Source, [string]$Destination) {
    $script:replaceAttempts += 1
    if ($replaceMode -eq 'transient' -and $replaceAttempts -le 2) {
        throw [IO.IOException]::new('Simulated sharing violation.', -2147024864)
    }
    if ($replaceMode -eq 'permission') {
        throw [UnauthorizedAccessException]::new('Simulated permission failure.')
    }
    [IO.File]::Replace($Source, $Destination, [NullString]::Value)
}
function Open-FixtureDownload([string]$Uri) {
    $requests.Add($Uri)
    $script:downloadAttempts += 1
    if ($downloadMode -eq 'retry' -and $downloadAttempts -eq 1) { throw 'Simulated interrupted connection.' }
    if ($downloadMode -eq 'empty') {
        return [pscustomobject]@{ Stream = [IO.MemoryStream]::new(); Length = 0; Response = $null }
    }
    if ($downloadMode -eq 'truncated') {
        return [pscustomobject]@{ Stream = [IO.MemoryStream]::new([byte[]](1, 2, 3)); Length = 999; Response = $null }
    }
    if (-not $Uri.EndsWith('/' + $fixtureAsset)) { throw "Unexpected archive: $Uri" }
    return [pscustomobject]@{ Stream = [IO.File]::OpenRead($archiveFixture); Length = $(if ($downloadMode -eq 'unknown') { -1 } else { (Get-Item -LiteralPath $archiveFixture).Length }); Response = $null }
}

function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [int]$TimeoutSec)
    $requests.Add($Uri)
    if ($Uri.EndsWith('/releases/latest')) {
        [IO.File]::WriteAllText($OutFile, ('{"tag_name":"v' + $fixtureVersion + '"}'))
    } elseif ($Uri -ceq "https://github.com/0v3rf3ar/Eirene/releases/download/v$fixtureVersion/SHA256SUMS") {
        $hash = if ($corrupt) { '0' * 64 } else { $checksumFixture }
        $shellHash = (Get-FileHash -LiteralPath (Join-Path $root 'install.sh') -Algorithm SHA256).Hash
        [IO.File]::WriteAllText($OutFile, "$hash  $fixtureAsset`n$shellHash  install.sh`n")
    } elseif ($Uri -ceq "https://github.com/0v3rf3ar/Eirene/releases/download/v$fixtureVersion/$fixtureAsset") {
        Copy-Item -LiteralPath $archiveFixture -Destination $OutFile
    } elseif ($Uri.EndsWith('/install.sh')) {
        Copy-Item -LiteralPath (Join-Path $root 'install.sh') -Destination $OutFile
    } else {
        throw "Unexpected download: $Uri"
    }
}

try {
    # First install and an atomic upgrade into a path with spaces.
    & $installer -Version latest -InstallDir $installDirectory -NoPathUpdate
    & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate
    $name = if ($Target -eq 'windows-amd64') { 'eirene.exe' } else { 'eirene' }
    $binary = Join-Path $installDirectory $name
    $originalHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
    & $binary --version
    if ($LASTEXITCODE -ne 0) { throw 'Installed binary is not executable.' }
    if (-not ($requests -contains "https://github.com/0v3rf3ar/Eirene/releases/download/v$fixtureVersion/$fixtureAsset")) {
        throw 'Installer chose the wrong release asset.'
    }
    $corrupt = $true
    $failed = $false
    try { & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate }
    catch {
        if ($_.Exception.Message -notmatch 'Checksum mismatch') { throw }
        $failed = $true
    }
    if (-not $failed) { throw 'Installer accepted a checksum mismatch.' }
    if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) {
        throw 'Failed install modified the existing executable.'
    }
    $corrupt = $false
    foreach ($failureMode in @('empty', 'truncated')) {
        $downloadMode = $failureMode
        $downloadAttempts = 0
        $failed = $false
        try { & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate }
        catch {
            if ($_.Exception.Message -notmatch 'archive is empty|download was incomplete') { throw }
            $failed = $true
        }
        if (-not $failed -or $downloadAttempts -ne 4) { throw "Expected four failed $failureMode download attempts." }
        if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) {
            throw 'Failed streaming download modified the existing executable.'
        }
    }
    $downloadMode = 'retry'
    $downloadAttempts = 0
    & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate
    if ($downloadAttempts -ne 2) { throw 'Interrupted download was not retried exactly once.' }
    $downloadMode = 'unknown'
    & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate
    if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) { throw 'Unknown-size download changed the fixture binary.' }
    $downloadMode = 'normal'
    if ($Target -eq 'windows-amd64') {
        $replaceMode = 'transient'
        $replaceAttempts = 0
        & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate
        if ($replaceAttempts -lt 3) { throw 'Transient replacement locks were not retried.' }
        $replaceMode = 'permission'
        $replaceAttempts = 0
        $failed = $false
        try { & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate }
        catch {
            if ($_.Exception.Message -notmatch 'Simulated permission failure') { throw }
            $failed = $true
        }
        if (-not $failed -or $replaceAttempts -ne 1) { throw 'Permission failures must not be retried.' }
        $replaceMode = 'normal'
        $replaceAttempts = 0
        $locked = [IO.File]::Open($binary, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        $failed = $false
        try { & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate }
        catch {
            if ($_.Exception.Message -notmatch 'executable is locked') { throw }
            $failed = $true
        } finally { $locked.Dispose() }
        if (-not $failed -or $replaceAttempts -ne 26) { throw 'A persistent lock must fail after 26 bounded attempts.' }
        if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) {
            throw 'Locked-executable failure modified the existing installation.'
        }
    }
    $env:EIRENE_NO_PATH = '0'
    if ($Target -ne 'windows-amd64') {
        $profileFixture = Join-Path $testRoot 'profile.ps1'
        [IO.File]::WriteAllText($profileFixture, "# existing user settings`n")
        $PROFILE = [pscustomobject]@{ CurrentUserAllHosts = $profileFixture }
    }
    # Repeat PATH setup, including when this process already has the directory.
    & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory
    & $installer -Version "v$fixtureVersion" -InstallDir $installDirectory
    if (($env:PATH -split [IO.Path]::PathSeparator) -notcontains $installDirectory) {
        throw 'Current terminal PATH was not updated.'
    }
    if ($Target -eq 'windows-amd64') {
        $entries = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';'
        if (@($entries | Where-Object { $_ -eq $installDirectory }).Count -ne 1) {
            throw 'Persistent user PATH must contain the install directory exactly once.'
        }
        $originalEntries = @($savedUserPath -split ';' | Where-Object { $_ })
        foreach ($entry in $originalEntries) {
            if ($entries -notcontains $entry) { throw "Existing PATH entry was lost: $entry" }
        }
    } else {
        $profileText = [IO.File]::ReadAllText($profileFixture)
        if (-not $profileText.StartsWith('# existing user settings')) { throw 'Profile was overwritten.' }
        if ([regex]::Matches($profileText, '# Eirene').Count -ne 1) { throw 'Profile update is not idempotent.' }
        $backups = @(Get-ChildItem -LiteralPath $testRoot -Filter 'profile.ps1.eirene-backup.*')
        if ($backups.Count -ne 1) { throw 'Expected one profile backup.' }
        # Evaluate the generated profile from a clean PATH to verify quoting.
        $env:PATH = $savedProcessPath
        . $profileFixture
        if (($env:PATH -split [IO.Path]::PathSeparator) -notcontains $installDirectory) {
            throw 'Saved profile did not restore PATH.'
        }
    }
    Write-Host 'PowerShell installer tests passed.'
} finally {
    $env:PATH = $savedProcessPath
    $env:EIRENE_NO_PATH = $savedNoPath
    $env:HOME = $savedHomeEnv
    $env:XDG_CONFIG_HOME = $savedConfigHome
    $env:ZDOTDIR = $savedZdotdir
    $env:SHELL = $savedShell
    $PROFILE = $savedProfile
    if ($Target -eq 'windows-amd64') {
        [Environment]::SetEnvironmentVariable('Path', $savedUserPath, 'User')
    }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}

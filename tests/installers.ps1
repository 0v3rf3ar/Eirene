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
$savedProcessPath = $env:PATH
$savedUserPath = if ($Target -eq 'windows-amd64') { [Environment]::GetEnvironmentVariable('Path', 'User') } else { $null }
$savedProfile = $PROFILE
$savedNoPath = $env:EIRENE_NO_PATH

function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [int]$TimeoutSec)
    $requests.Add($Uri)
    if ($Uri.EndsWith('/releases/latest')) {
        [IO.File]::WriteAllText($OutFile, ('{"tag_name":"v' + $fixtureVersion + '"}'))
    } elseif ($Uri -ceq "https://github.com/0v3rf3ar/Eirene/releases/download/v$fixtureVersion/SHA256SUMS") {
        $hash = if ($corrupt) { '0' * 64 } else { $checksumFixture }
        [IO.File]::WriteAllText($OutFile, "$hash  $fixtureAsset`n")
    } elseif ($Uri -ceq "https://github.com/0v3rf3ar/Eirene/releases/download/v$fixtureVersion/$fixtureAsset") {
        Copy-Item -LiteralPath $archiveFixture -Destination $OutFile
    } else {
        throw "Unexpected download: $Uri"
    }
}

try {
    # First install and an atomic upgrade into a path with spaces.
    & "$root/install.ps1" -Version latest -InstallDir $installDirectory -NoPathUpdate
    & "$root/install.ps1" -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate
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
    try { & "$root/install.ps1" -Version "v$fixtureVersion" -InstallDir $installDirectory -NoPathUpdate }
    catch {
        if ($_.Exception.Message -notmatch 'Checksum mismatch') { throw }
        $failed = $true
    }
    if (-not $failed) { throw 'Installer accepted a checksum mismatch.' }
    if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) {
        throw 'Failed install modified the existing executable.'
    }
    $corrupt = $false
    $env:EIRENE_NO_PATH = '0'
    if ($Target -ne 'windows-amd64') {
        $profileFixture = Join-Path $testRoot 'profile.ps1'
        [IO.File]::WriteAllText($profileFixture, "# existing user settings`n")
        $PROFILE = [pscustomobject]@{ CurrentUserAllHosts = $profileFixture }
    }
    # Repeat PATH setup, including when this process already has the directory.
    & "$root/install.ps1" -Version "v$fixtureVersion" -InstallDir $installDirectory
    & "$root/install.ps1" -Version "v$fixtureVersion" -InstallDir $installDirectory
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
    $PROFILE = $savedProfile
    if ($Target -eq 'windows-amd64') {
        [Environment]::SetEnvironmentVariable('Path', $savedUserPath, 'User')
    }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}

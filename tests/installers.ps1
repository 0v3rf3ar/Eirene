# Exercise the real installer against the locally built native release archive.
param([Parameter(Mandatory = $true)][string]$Target)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$extension = if ($Target -eq 'windows-amd64') { 'zip' } else { 'tar.gz' }
$version = (& python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read release version.' }
$label = @{'linux-amd64' = 'Linux-amd64'; 'linux-arm64' = 'Linux-arm64'; 'macos-silicon' = 'MacOS-silicon'; 'windows-amd64' = 'Windows-amd64'}[$Target]
$asset = "eirene-$label-$version.$extension"
$archiveFixture = Join-Path $root "release/$asset"
$checksumFixture = (Get-FileHash -LiteralPath $archiveFixture -Algorithm SHA256).Hash.ToLowerInvariant()
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('eirene-installer-test-' + [guid]::NewGuid().ToString('N'))
$installDirectory = Join-Path $testRoot 'path with spaces'
$requests = [Collections.Generic.List[string]]::new()
$corrupt = $false

function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [int]$TimeoutSec)
    $requests.Add($Uri)
    if ($Uri.EndsWith('/releases/latest')) {
        [IO.File]::WriteAllText($OutFile, ('{"tag_name":"v' + $version + '"}'))
    } elseif ($Uri.EndsWith('/SHA256SUMS')) {
        $hash = if ($corrupt) { '0' * 64 } else { $checksumFixture }
        [IO.File]::WriteAllText($OutFile, "$hash  $asset`n")
    } elseif ($Uri.EndsWith("/$asset")) {
        Copy-Item -LiteralPath $archiveFixture -Destination $OutFile
    } else {
        throw "Unexpected download: $Uri"
    }
}

try {
    # First install and an atomic upgrade into a path with spaces.
    & "$root/install.ps1" -Version latest -InstallDir $installDirectory -NoPathUpdate
    & "$root/install.ps1" -Version "v$version" -InstallDir $installDirectory -NoPathUpdate
    $name = if ($Target -eq 'windows-amd64') { 'eirene.exe' } else { 'eirene' }
    $binary = Join-Path $installDirectory $name
    $originalHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
    & $binary --version
    if ($LASTEXITCODE -ne 0) { throw 'Installed binary is not executable.' }
    if (-not ($requests -contains "https://github.com/0v3rf3ar/Eirene/releases/download/v$version/$asset")) {
        throw 'Installer chose the wrong release asset.'
    }
    $corrupt = $true
    $failed = $false
    try { & "$root/install.ps1" -Version "v$version" -InstallDir $installDirectory -NoPathUpdate }
    catch {
        if ($_.Exception.Message -notmatch 'Checksum mismatch') { throw }
        $failed = $true
    }
    if (-not $failed) { throw 'Installer accepted a checksum mismatch.' }
    if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $originalHash) {
        throw 'Failed install modified the existing executable.'
    }
    Write-Host 'PowerShell installer tests passed.'
} finally {
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}

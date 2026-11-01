# Fetches 7-Zip's newest release for Windows x64, unpacks 7z.exe, 7z.dll
# and License.txt into -Destination, and prints the version it fetched,
# as GitHub tags it.
#
# 7-zip.org links its downloads from the releases of github.com/ip7z/7zip,
# whose "latest" is the newest release that is not a pre-release.  The
# installer is checked against the SHA-256 GitHub gives for it.  The
# runner's own 7-Zip, which unpacks it, comes with the runner's image and
# can be a release behind.
param(
    [Parameter(Mandatory)] [string] $Destination,
    # 7-Zip unpacks the installer without running it.
    [string] $SevenZip = "$env:ProgramFiles/7-Zip/7z.exe",
    # Optional; GitHub limits API requests without a token by address,
    # which runners share.
    [string] $Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = 'Stop'

$headers = @{ 'Accept' = 'application/vnd.github+json' }
if ($Token) { $headers['Authorization'] = "Bearer $Token" }
$release = Invoke-RestMethod 'https://api.github.com/repos/ip7z/7zip/releases/latest' -Headers $headers
$asset = @($release.assets | Where-Object { $_.name -match '^7z\d+-x64\.exe$' })
if ($asset.Count -ne 1) { throw "7-Zip $($release.tag_name) has no single x64 installer" }
$asset = $asset[0]
if ($asset.digest -notmatch '^sha256:([0-9a-f]{64})$') { throw "GitHub gives no SHA-256 for $($asset.name)" }
$expected = $Matches[1]

$installer = Join-Path ([System.IO.Path]::GetTempPath()) "7zip-$PID.exe"
Invoke-WebRequest $asset.browser_download_url -OutFile $installer
$actual = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    Remove-Item $installer
    throw "$($asset.name) has SHA-256 $actual, GitHub gives $expected"
}

New-Item -ItemType Directory -Force $Destination | Out-Null
& $SevenZip e $installer 7z.exe 7z.dll License.txt "-o$Destination" -y | Out-Null
if ($LASTEXITCODE) { throw "7-Zip could not unpack $($asset.name)" }
Remove-Item $installer

$release.tag_name

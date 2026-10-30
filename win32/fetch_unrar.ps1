# Fetches RARLAB's UnRAR.dll, the newest that is not a beta, unpacks
# UnRAR64.dll and its license.txt into -Destination, and prints the
# version it fetched, such as 7.13.
#
# RARLAB links its newest UnRAR.dll from rar_add.htm, a beta as often as
# not; the newest release below a beta is looked for by number.  The
# release workflow bundles what this fetches with the Windows packages,
# and the Windows tests load it as MComix.exe does.
param(
    [Parameter(Mandatory)] [string] $Destination,
    # 7-Zip unpacks the installer without running it.
    [string] $SevenZip = "$env:ProgramFiles/7-Zip/7z.exe"
)

$ErrorActionPreference = 'Stop'

$page = (Invoke-WebRequest 'https://www.rarlab.com/rar_add.htm').Content
if ($page -notmatch 'rar/unrardll-(\d+)(b\d+)?\.exe') { throw 'rar_add.htm links no UnRAR.dll' }
$linked = $Matches[0]
$number = [int]$Matches[1]
$candidates = if ($Matches[2]) { ($number - 1)..($number - 30) } else { @($number) }

$installer = Join-Path ([System.IO.Path]::GetTempPath()) "unrardll-$PID.exe"
$unrar = $null
foreach ($candidate in $candidates) {
    try {
        Invoke-WebRequest "https://www.rarlab.com/rar/unrardll-$candidate.exe" -OutFile $installer
        $unrar = $candidate
        break
    } catch { }
}
if (-not $unrar) { throw "No released UnRAR.dll below the one rar_add.htm links, $linked" }

New-Item -ItemType Directory -Force $Destination | Out-Null
& $SevenZip e $installer x64/UnRAR64.dll license.txt "-o$Destination" -y | Out-Null
if ($LASTEXITCODE) { throw "7-Zip could not unpack UnRAR.dll $unrar" }
Remove-Item $installer

# 713 is UnRAR 7.13.
$unrar.ToString().Insert(1, '.')

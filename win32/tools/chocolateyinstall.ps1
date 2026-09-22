$ErrorActionPreference = 'Stop'

$packageName = $env:ChocolateyPackageName
$packageVersion = $env:ChocolateyPackageVersion
# MComix is numbered by year and month, as 26.10, and Chocolatey may
# give the package's version as 26.10.0; the release and the installer
# are named without the third number.
$releaseVersion = $packageVersion -replace '^(\d+\.\d+)\.0$', '$1'

# The checksum belongs to one build of one version, so it is not kept in
# the source tree: win32/build_msi.py writes it beside this script when
# it builds the installer named below, and `choco pack` ships it.
$checksumPath = Join-Path $PSScriptRoot 'checksum.sha256'
if (-not (Test-Path $checksumPath)) {
  throw "Missing $checksumPath - run win32\build_msi.py before packing."
}

$packageArgs = @{
  packageName   = $packageName
  fileType      = 'msi'
  softwareName  = 'MComix'
  # The installer's name is the one win32/build_msi.py gives it, which
  # is not the package's.
  url64bit      =  "https://github.com/twwn/mcomix/releases/download/$releaseVersion/mcomix-win64-$releaseVersion.msi"
  checksum64    = (Get-Content $checksumPath -Raw).Trim()
  checksumType64=  'sha256'
  silentArgs    = "/qn /norestart /l*v `"$($env:TEMP)\$($packageName).$($env:chocolateyPackageVersion).MsiInstall.log`""
  validExitCodes= @(0, 3010, 1641)
}

Install-ChocolateyPackage @packageArgs

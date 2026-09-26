$ErrorActionPreference = 'Stop'

$packageName = $env:ChocolateyPackageName

# The checksum and the release belong to one build of one version, so
# they are not kept in the source tree: win32/build_msi.py writes both
# beside this script when it builds the installer named below, and
# `choco pack` ships them.  The release is read from there rather than
# from the package's version, which Chocolatey gives back as a number:
# 26.9.0 for the release 26.09.
$checksumPath = Join-Path $PSScriptRoot 'checksum.sha256'
$releasePath = Join-Path $PSScriptRoot 'release.txt'
foreach ($path in $checksumPath, $releasePath) {
  if (-not (Test-Path $path)) {
    throw "Missing $path - run win32\build_msi.py before packing."
  }
}
$releaseVersion = (Get-Content $releasePath -Raw).Trim()

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

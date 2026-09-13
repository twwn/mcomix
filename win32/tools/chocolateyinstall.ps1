$ErrorActionPreference = 'Stop'

$packageName = $env:ChocolateyPackageName
$packageTitle = $env:ChocolateyPackageTitle
$packageVersion = $env:ChocolateyPackageVersion

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
  url64bit      =  "https://sourceforge.net/projects/$packageName/files/$packageTitle-$packageVersion/$packageName-win64-$packageVersion.msi/download"
  checksum64    = (Get-Content $checksumPath -Raw).Trim()
  checksumType64=  'sha256'
  silentArgs    = "/qn /norestart /l*v `"$($env:TEMP)\$($packageName).$($env:chocolateyPackageVersion).MsiInstall.log`""
  validExitCodes= @(0, 3010, 1641)
}

Install-ChocolateyPackage @packageArgs

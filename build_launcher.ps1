$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceFile = Join-Path $projectRoot "PromptToolLauncher.cs"
$outputFile = Join-Path $projectRoot "PromptToolLauncher.exe"
$temporaryOutput = Join-Path $projectRoot "PromptToolLauncher.build.exe"
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $compiler)) {
    throw "The .NET Framework C# compiler was not found: $compiler"
}
# A console application keeps startup/server logs visible after double-clicking.
# Compile before replacing the old EXE; this also works in PowerShell 7.
try {
    & $compiler /nologo /target:exe /optimize+ /reference:System.Net.Http.dll "/out:$temporaryOutput" $sourceFile
    if ($LASTEXITCODE -ne 0) { throw "Launcher compilation failed ($LASTEXITCODE)." }
    Move-Item -LiteralPath $temporaryOutput -Destination $outputFile -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryOutput) {
        Remove-Item -LiteralPath $temporaryOutput -Force
    }
}
Write-Host "Built launcher:" $outputFile

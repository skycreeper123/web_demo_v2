$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceFile = Join-Path $projectRoot "PromptToolLauncher.cs"
$outputFile = Join-Path $projectRoot "PromptToolLauncher.exe"

if (-not (Test-Path $sourceFile)) {
    throw "Missing source file: $sourceFile"
}

if (Test-Path $outputFile) {
    Remove-Item -LiteralPath $outputFile -Force
}

$source = Get-Content -Raw -LiteralPath $sourceFile

Add-Type `
    -TypeDefinition $source `
    -Language CSharp `
    -ReferencedAssemblies @(
        "System.dll",
        "System.Net.Http.dll",
        "System.Windows.Forms.dll"
    ) `
    -OutputAssembly $outputFile `
    -OutputType WindowsApplication

Write-Host "Built launcher:" $outputFile

# Export Script for Tesco Price Tracker Extension
# usage: .\export.ps1

$ErrorActionPreference = "Stop"

# 1. Read version from manifest.json
$manifestPath = "extension\manifest.json"
if (-not (Test-Path $manifestPath)) {
    Write-Error "manifest.json not found at $manifestPath"
}

$manifestContent = Get-Content $manifestPath -Raw | ConvertFrom-Json
$version = $manifestContent.version
Write-Host "Detected version: $version" -ForegroundColor Cyan

# 2. Prepare output directory
$outputDir = "versions"
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
    Write-Host "Created '$outputDir' directory" -ForegroundColor Gray
}

$zipFileName = "TescoPriceTracker-v$version.zip"
$zipFilePath = Join-Path $outputDir $zipFileName

if (Test-Path $zipFilePath) {
    Write-Warning "File '$zipFileName' already exists. Overwriting..."
    Remove-Item $zipFilePath
}

# 3. Define files/folders to include
# We want to zip the *contents* of the extension folder, not the extension folder itself
# So the root of the zip should contain manifest.json
$sourceDir = "extension"
$itemsToZip = @(
    "manifest.json",
    "background",
    "content",
    "icons",
    "popup"
)

# 4. Create the Zip file
Write-Host "Creating $zipFileName..." -ForegroundColor Yellow

# Use Compress-Archive
# We need to pass the full paths of the items inside the extension folder
$compressionSource = $itemsToZip | ForEach-Object { Join-Path $sourceDir $_ }

Compress-Archive -Path $compressionSource -DestinationPath $zipFilePath -CompressionLevel Optimal

if (Test-Path $zipFilePath) {
    Write-Host "SUCCESS! Exported to: $zipFilePath" -ForegroundColor Green
    Write-Host "Ready to upload to Chrome Web Store, Firefox Add-ons, and Edge Add-ons." -ForegroundColor Gray
} else {
    Write-Error "Failed to create zip file."
}

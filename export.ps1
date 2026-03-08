# Export Script for Tesco Price Tracker Extension
# usage: .\export.ps1

$ErrorActionPreference = "Stop"

# Load required assembly for ZipFile
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Add-Type -AssemblyName System.IO.Compression
} catch {
    Write-Error "Failed to load System.IO.Compression assemblies. Ensure .NET Framework 4.5+ is installed."
}

# 1. Read version from manifest.json
$manifestPath = "extension\manifest.json"
if (-not (Test-Path $manifestPath)) {
    Write-Error "manifest.json not found at $manifestPath" -ForegroundColor Red
    exit 1
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
$outputDirAbs = (Resolve-Path $outputDir).Path
$zipFilePath = Join-Path $outputDirAbs $zipFileName

if (Test-Path $zipFilePath) {
    Write-Warning "File '$zipFileName' already exists. Overwriting..."
    Remove-Item $zipFilePath -Force
}

# 3. Define files/folders to include
$sourceDir = "extension"
if (-not (Test-Path $sourceDir)) {
    Write-Error "Source directory '$sourceDir' not found."
}
$sourceDirAbs = (Resolve-Path $sourceDir).Path

$itemsToZip = @(
    "manifest.json",
    "background",
    "content",
    "icons",
    "popup"
)

# 4. Create the Zip file using System.IO.Compression to enforce forward slashes
Write-Host "Creating $zipFileName..." -ForegroundColor Yellow

try {
    $zip = [System.IO.Compression.ZipFile]::Open($zipFilePath, [System.IO.Compression.ZipArchiveMode]::Create)

    foreach ($item in $itemsToZip) {
        $fullPath = Join-Path $sourceDirAbs $item
        
        if (Test-Path $fullPath -PathType Leaf) {
            # File
            $entryName = $item.Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $fullPath, $entryName) | Out-Null
        }
        elseif (Test-Path $fullPath -PathType Container) {
            # Directory
            # Recurse and add all files
            $files = Get-ChildItem -Path $fullPath -Recurse -File
            foreach ($file in $files) {
                 # Make path relative to sourceDir (extension root)
                 $relativePath = $file.FullName.Substring($sourceDirAbs.Length + 1)
                 $entryName = $relativePath.Replace('\', '/')
                 [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $entryName) | Out-Null
            }
        }
        else {
            Write-Warning "Item '$item' not found in '$sourceDir', skipping."
        }
    }
}
catch {
    Write-Error "An error occurred during zip creation: $_"
}
finally {
    if ($zip) {
        $zip.Dispose()
    }
}

Write-Host "SUCCESS! Exported to: $zipFilePath" -ForegroundColor Green

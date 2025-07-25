# PowerShell script to build Crystal on Windows with minimal output
# Only shows output when there are errors/warnings

# Run the build and capture output
$buildOutput = ""
$buildFailed = $false

try {
    # Capture all output from the build process
    $buildOutput = poetry run .\make-win.bat 2>&1 | Out-String
    
    # Check if build was successful by looking for the exit code
    if ($LASTEXITCODE -ne 0) {
        $buildFailed = $true
    }
} catch {
    $buildFailed = $true
    $buildOutput += "Exception occurred: $($_.Exception.Message)`n"
}

# Only show output if there were errors/warnings or build failed
if ($buildFailed -or $buildOutput -match "(error|warning|failed|exception)" -and $buildOutput -notmatch "(?i)missing *modules") {
    Write-Host $buildOutput
} else {
    Write-Host "Build completed successfully (output suppressed - no errors/warnings detected)"
}

# Exit with error code if build failed
if ($buildFailed) {
    exit $LASTEXITCODE
}

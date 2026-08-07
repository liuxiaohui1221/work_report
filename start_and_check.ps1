# Start Flask server in background and check
$ErrorActionPreference = "SilentlyContinue"

# Kill any existing python processes on port 5000
$connections = netstat -ano | Select-String ":5000"
if ($connections) {
    Write-Host "Found existing connections on port 5000, will kill them..."
    $connections | ForEach-Object {
        $parts = $_ -split '\s+'
        $pid = $parts[-1]
        if ($pid -and $pid -ne "0") {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
}

Start-Sleep -Seconds 1

# Start server
$env:PYTHONUNBUFFERED = "1"
$process = Start-Process -FilePath "python" -ArgumentList "-m main.app" -WorkingDirectory "C:\workspace\pywork\work_report" -NoNewWindow -PassThru -RedirectStandardOutput "server.log" -RedirectStandardError "server.err"

# Wait for server to start
Start-Sleep -Seconds 3

# Check if running
if ($process -and -not $process.HasExited) {
    Write-Host "Server started with PID:" $process.Id
} else {
    Write-Host "Server failed to start, checking logs..."
    if (Test-Path "server.err") {
        Get-Content "server.err" | Select-Object -First 10
    }
}

# Check port
$listening = netstat -ano | Select-String "LISTENING" | Select-String ":5000"
if ($listening) {
    Write-Host "Port 5000 is now listening!"
    Write-Host $listening
} else {
    Write-Host "Port 5000 still not listening"
    Write-Host "Checking server output..."
    if (Test-Path "server.log") {
        Get-Content "server.log" | Select-Object -First 10
    }
}
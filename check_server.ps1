# Check if server is running
$response = Invoke-WebRequest -Uri "http://127.0.0.1:5000/new" -TimeoutSec 5 -ErrorAction SilentlyContinue
if ($response) {
    Write-Host "Server is running!"
    Write-Host "Status:" $response.StatusCode
    Write-Host "Content length:" $response.Content.Length
} else {
    Write-Host "Server not accessible"
    Write-Host "Trying to check port..."
    $connections = netstat -ano | Select-String ":5000"
    if ($connections) {
        Write-Host "Port 5000 is in use:"
        $connections | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "Port 5000 is not listening"
    }
}
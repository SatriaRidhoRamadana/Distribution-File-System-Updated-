# Setup dan run test suite dengan mudah

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "DFS TEST SUITE LAUNCHER" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

Write-Host "`nPilih test yang ingin dijalankan:" -ForegroundColor Yellow
Write-Host "1. test_upload_replic.py (Quick - 5 seconds)" -ForegroundColor Green
Write-Host "2. list_files.py (Show all files)" -ForegroundColor Green
Write-Host "3. verify_metadata.py (Verify consistency)" -ForegroundColor Green
Write-Host "4. test_recovery_replication.py (Auto - 70 seconds)" -ForegroundColor Blue
Write-Host "5. test_recovery_manual.py (Manual Demo - 2 minutes)" -ForegroundColor Magenta
Write-Host "0. Exit" -ForegroundColor Red

$choice = Read-Host "`nMasukkan pilihan (0-5)"

# Set UTF-8 encoding
$env:PYTHONIOENCODING='utf-8'

switch ($choice) {
    "1" {
        Write-Host "`nRunning test_upload_replic.py..." -ForegroundColor Green
        python test_upload_replic.py
    }
    "2" {
        Write-Host "`nRunning list_files.py..." -ForegroundColor Green
        python list_files.py
    }
    "3" {
        Write-Host "`nRunning verify_metadata.py..." -ForegroundColor Green
        python verify_metadata.py
    }
    "4" {
        Write-Host "`nRunning test_recovery_replication.py (AUTOMATIC)..." -ForegroundColor Blue
        Write-Host "This will take about 70 seconds" -ForegroundColor Cyan
        Write-Host "Make sure naming_service.py and all 3 storage nodes are running!" -ForegroundColor Yellow
        python test_recovery_replication.py
    }
    "5" {
        Write-Host "`nRunning test_recovery_manual.py (DEMO MODE)..." -ForegroundColor Magenta
        Write-Host "This will guide you through recovery test step-by-step" -ForegroundColor Cyan
        Write-Host "Make sure naming_service.py and all 3 storage nodes are running!" -ForegroundColor Yellow
        python test_recovery_manual.py
    }
    "0" {
        Write-Host "`nExiting..." -ForegroundColor Red
        exit
    }
    default {
        Write-Host "`nInvalid choice!" -ForegroundColor Red
    }
}

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host "Test completed!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan

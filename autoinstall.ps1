# ==========================================
# Windows App Installer via Winget
# Source : winget
# ==========================================

Write-Host "Checking Winget..." -ForegroundColor Cyan

if (!(Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "Winget tidak ditemukan. Install App Installer dari Microsoft Store." -ForegroundColor Red
    exit
}

# Daftar aplikasi
$apps = @(
    "FastStone.Viewer",
    "VideoLAN.VLC",
    "SumatraPDF.SumatraPDF",
    "RARLab.WinRAR",
    "Notepad++.Notepad++",
    "CapCut.CapCut",
    "Spotify.Spotify",
    "Canva.Canva",
    "Serif.AffinityDesigner"
)

Write-Host ""
Write-Host "Mulai instalasi aplikasi..." -ForegroundColor Green
Write-Host ""

foreach ($app in $apps) {

    Write-Host "Installing: $app" -ForegroundColor Yellow

    winget install `
        --id $app `
        --source winget `
        --silent `
        --accept-package-agreements `
        --accept-source-agreements

    if ($LASTEXITCODE -eq 0) {
        Write-Host "$app berhasil dipasang" -ForegroundColor Green
    }
    else {
        Write-Host "$app gagal atau sudah terinstall" -ForegroundColor Red
    }

    Write-Host "--------------------------------"
}

Write-Host ""
Write-Host "Semua proses selesai." -ForegroundColor Cyan
Pause

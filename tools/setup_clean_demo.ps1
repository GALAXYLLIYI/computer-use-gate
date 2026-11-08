#requires -Version 7.0
<#
.SYNOPSIS
    Prepare a clean, privacy-safe demo desktop.
    - backs up current wallpaper + desktop icon visibility
    - sets a solid wallpaper
    - hides desktop icons
    - closes only the demo Notepad/Calculator windows if present
    - opens fresh Notepad + Calculator and places them inside the recording area
#>
[CmdletBinding()]
param(
    [string]$Wallpaper = '',
    [switch]$SkipApps
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$demoDir = Join-Path $env:USERPROFILE 'AgentCtlDemo'
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$backupFile = Join-Path $demoDir 'desktop-backup.json'
$assets = Join-Path $repo 'assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null

if (-not $Wallpaper) { $Wallpaper = Join-Path $assets 'demo-wallpaper.png' }
$ffmpeg = 'F:\ZhuanZ\Documents\tools\ffmpeg-9.0\ffmpeg-n9.0-latest-win64-gpl-9.0\bin\ffmpeg.exe'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class CleanDesktop {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@
[CleanDesktop]::SetProcessDPIAware() | Out-Null

# 1. Backup current desktop settings
$desk = Get-ItemProperty 'HKCU:\Control Panel\Desktop' -ErrorAction SilentlyContinue
$adv = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -ErrorAction SilentlyContinue
$backup = [ordered]@{
    wallpaper     = if ($desk) { [string]$desk.Wallpaper } else { '' }
    wallpaperStyle = if ($desk) { [string]$desk.WallpaperStyle } else { '10' }
    tileWallpaper = if ($desk) { [string]$desk.TileWallpaper } else { '0' }
    hideIcons     = if ($adv -and $null -ne $adv.HideIcons) { [int]$adv.HideIcons } else { 0 }
    createdAt     = (Get-Date).ToString('o')
}
$backup | ConvertTo-Json -Depth 4 | Set-Content -Path $backupFile -Encoding UTF8
Write-Host "backup: $backupFile"

# 2. Generate a solid wallpaper
if (-not (Test-Path $Wallpaper)) {
    & $ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=0x0f172a:s=2560x1600' -frames:v 1 -y $Wallpaper
    if ($LASTEXITCODE -ne 0) { throw "wallpaper generation failed" }
}
Write-Host "wallpaper: $Wallpaper"

# 3. Apply wallpaper
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name Wallpaper -Value $Wallpaper
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name WallpaperStyle -Value '10'   # fill
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name TileWallpaper -Value '0'
[CleanDesktop]::SystemParametersInfo(20, 0, $Wallpaper, 3) | Out-Null

# 4. Hide desktop icons
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -Name HideIcons -Value 1 -Type DWord
[CleanDesktop]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Milliseconds 800

# 5. Close only the demo apps we started, then reopen clean
if (-not $SkipApps) {
    Get-Process notepad,CalculatorApp,Calculator -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'demo\.txt|计算器|Calculator' -or $_.ProcessName -match 'Calculator' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    $file = Join-Path $demoDir 'demo.txt'
    "AgentCtl demo file.`r`nThis file is safe to edit.`r`nNo private data here." | Set-Content -Path $file -Encoding UTF8
    $np = Start-Process notepad.exe -ArgumentList "`"$file`"" -PassThru
    Start-Sleep -Seconds 2
    $calc = Start-Process calc.exe -PassThru
    Start-Sleep -Seconds 3

    $npProc = Get-Process -Id $np.Id -ErrorAction SilentlyContinue
    if ($npProc -and $npProc.MainWindowHandle -ne 0) {
        [CleanDesktop]::MoveWindow($npProc.MainWindowHandle, 900, 320, 900, 700, $true) | Out-Null
        [CleanDesktop]::SetForegroundWindow($npProc.MainWindowHandle) | Out-Null
    }
    $calcWin = Get-Process | Where-Object { $_.MainWindowTitle -match '计算器|Calculator' } | Select-Object -First 1
    if ($calcWin -and $calcWin.MainWindowHandle -ne 0) {
        [CleanDesktop]::MoveWindow($calcWin.MainWindowHandle, 400, 320, 450, 600, $true) | Out-Null
    }
    Write-Host "notepad_pid=$($np.Id) calc_pid=$($calc.Id)"
}

Write-Host 'clean desktop ready.'
Write-Host 'Run restore_clean_demo.ps1 after recording to restore wallpaper/icons.'

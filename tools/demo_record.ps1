#requires -Version 7.0
<#
.SYNOPSIS
    Record the 60-second computer-use-gate demo on a clean Windows desktop.

.DESCRIPTION
    This script does not operate the agent. It prepares a safe demo area,
    opens Notepad + Calculator, records a fixed 1920x1080 region with ffmpeg,
    then creates the MP4 and GIF used by README.

    Recommended: create a new virtual desktop first (Win+Ctrl+D), put only
    Notepad and Calculator there, then run this script from that desktop.

.EXAMPLE
    pwsh -File .\tools\demo_record.ps1 -DryRun

.EXAMPLE
    pwsh -File .\tools\demo_record.ps1
#>
[CmdletBinding()]
param(
    [string]$Ffmpeg = 'F:\ZhuanZ\Documents\tools\ffmpeg-9.0\ffmpeg-n9.0-latest-win64-gpl-9.0\bin\ffmpeg.exe',
    [string]$OutDir = '',
    [int]$Width = 1920,
    [int]$Height = 1080,
    [int]$Duration = 75,
    [switch]$SkipApps,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $repo 'assets' }
$OutDir = [IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $Ffmpeg)) {
    throw "ffmpeg not found: $Ffmpeg"
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class DemoWin32 {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
    [DllImport("user32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
'@

[DemoWin32]::SetProcessDPIAware() | Out-Null
$screenW = [DemoWin32]::GetSystemMetrics(0)
$screenH = [DemoWin32]::GetSystemMetrics(1)
$w = [Math]::Min($Width, $screenW)
$h = [Math]::Min($Height, $screenH)
$w = $w - ($w % 2)
$h = $h - ($h % 2)
$x = [Math]::Floor(($screenW - $w) / 2)
$y = [Math]::Floor(($screenH - $h) / 2)

$demoDir = Join-Path $env:USERPROFILE 'AgentCtlDemo'
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$demoFile = Join-Path $demoDir 'demo.txt'
@'
AgentCtl demo file.
This file is safe to edit. It contains no private data.
'@ | Set-Content -Path $demoFile -Encoding UTF8

$raw = Join-Path $OutDir 'demo-raw.mp4'
$final = Join-Path $OutDir 'demo-60s.mp4'
$gif = Join-Path $OutDir 'demo-60s.gif'
$log = Join-Path $OutDir 'demo-ffmpeg.log'

$ffArgs = @(
    '-hide_banner', '-loglevel', 'warning',
    '-f', 'gdigrab', '-framerate', '30',
    '-offset_x', "$x", '-offset_y', "$y",
    '-video_size', "$w`x$h",
    '-i', 'desktop',
    '-t', "$Duration",
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
    '-pix_fmt', 'yuv420p', '-y', $raw
)

Write-Host ''
Write-Host '=== computer-use-gate demo recorder ===' -ForegroundColor Cyan
Write-Host "screen : ${screenW}x${screenH}"
Write-Host "region : ${w}x${h} at (${x},${y})"
Write-Host "raw    : $raw"
Write-Host "final  : $final"
Write-Host "gif    : $gif"
Write-Host ''
Write-Host 'Before recording:' -ForegroundColor Yellow
Write-Host '  1. Press Win+Ctrl+D to create a clean virtual desktop (recommended).'
Write-Host '  2. Keep only Notepad and Calculator on it; close chat/browser windows.'
Write-Host '  3. Hide desktop icons if they fall inside the recording region.'
Write-Host '  4. The authorization popup must be clicked by YOU. Do not automate it.'
Write-Host ''

if ($DryRun) {
    Write-Host '[DryRun] would open Notepad with:' $demoFile
    Write-Host '[DryRun] would open Calculator'
    Write-Host '[DryRun] ffmpeg args:'
    Write-Host ('  ' + $Ffmpeg + ' ' + ($ffArgs -join ' '))
    Write-Host '[DryRun] no files were recorded.'
    exit 0
}

$notepad = $null
$calc = $null
if (-not $SkipApps) {
    Write-Host 'Opening Notepad and Calculator...' -ForegroundColor Cyan
    $notepad = Start-Process notepad.exe -ArgumentList "`"$demoFile`"" -PassThru
    Start-Sleep -Milliseconds 700
    $calc = Start-Process calc.exe -PassThru
    Start-Sleep -Seconds 2
    Write-Host 'Arrange them: Notepad left, Calculator right. Then press Enter.' -ForegroundColor Yellow
    [void](Read-Host)
} else {
    Write-Host 'SkipApps: arrange your demo windows manually, then press Enter.' -ForegroundColor Yellow
    [void](Read-Host)
}

Write-Host ''
Write-Host 'Cue card (the recording starts in 5 seconds):' -ForegroundColor Cyan
Write-Host '  0-10s  Show the desktop and the AgentCtl border.'
Write-Host '  10-25s Agent tries to click Save while the target window is wrong -> gate rejects.'
Write-Host '  25-35s Authorization popup -> YOU enter the key and click Authorize.'
Write-Host '  35-50s Agent clicks Save -> screen changes -> verdict "effective".'
Write-Host '  50-62s Show timeline / hash chain / replay.'
Write-Host '  62-72s Press Ctrl+Alt+Home -> border goes dark.'
Write-Host '  72-75s Hold on the repo URL or the panel.'
Write-Host ''
Write-Host 'Do not switch to this terminal while recording. It will minimize itself.' -ForegroundColor Yellow
for ($i = 5; $i -ge 1; $i--) {
    Write-Host "  starting in $i..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 1
}

$console = [DemoWin32]::GetConsoleWindow()
if ($console -ne [IntPtr]::Zero) {
    [DemoWin32]::ShowWindow($console, 6) | Out-Null
}
Start-Sleep -Milliseconds 600

Write-Host 'Recording...' -ForegroundColor Green
$proc = Start-Process -FilePath $Ffmpeg -ArgumentList $ffArgs -PassThru -WindowStyle Hidden -RedirectStandardError $log
$start = Get-Date
while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 500
    if (((Get-Date) - $start).TotalSeconds -gt ($Duration + 15)) {
        Write-Host 'Safety stop: ffmpeg did not exit in time.' -ForegroundColor Red
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        break
    }
}
try { $proc.WaitForExit(5000) | Out-Null } catch {}

if ($console -ne [IntPtr]::Zero) {
    [DemoWin32]::ShowWindow($console, 9) | Out-Null
}

if (-not (Test-Path $raw)) {
    Write-Host 'Recording failed. ffmpeg log:' -ForegroundColor Red
    if (Test-Path $log) { Get-Content $log -Tail 30 }
    exit 1
}

Write-Host ''
Write-Host 'Recording done. Building MP4 + GIF...' -ForegroundColor Cyan
& $Ffmpeg -hide_banner -loglevel warning -ss 3 -i $raw -t 65 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -y $final
if ($LASTEXITCODE -ne 0) { throw 'MP4 conversion failed' }

$palette = Join-Path $OutDir 'demo-palette.png'
& $Ffmpeg -hide_banner -loglevel warning -i $final -vf "fps=12,scale=960:-1:flags=lanczos,palettegen" -y $palette
if ($LASTEXITCODE -ne 0) { throw 'GIF palette generation failed' }
& $Ffmpeg -hide_banner -loglevel warning -i $final -i $palette -lavfi "fps=12,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse" -loop 0 -y $gif
if ($LASTEXITCODE -ne 0) { throw 'GIF conversion failed' }

Remove-Item $palette -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host 'Output:' -ForegroundColor Green
Get-Item $raw, $final, $gif | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
Write-Host 'Watch the video before publishing. If any private data appears, delete and re-record.' -ForegroundColor Yellow
Start-Process explorer.exe $OutDir

if ($notepad -and -not $notepad.HasExited) { Stop-Process -Id $notepad.Id -ErrorAction SilentlyContinue }
if ($calc -and -not $calc.HasExited) { Stop-Process -Id $calc.Id -ErrorAction SilentlyContinue }

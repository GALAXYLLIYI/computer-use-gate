#requires -Version 7.0
<#
.SYNOPSIS
    Restore the wallpaper and desktop icon visibility saved by setup_clean_demo.ps1.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$backupFile = Join-Path $env:USERPROFILE 'AgentCtlDemo\desktop-backup.json'
if (-not (Test-Path $backupFile)) {
    throw "backup not found: $backupFile"
}
$b = Get-Content $backupFile -Raw | ConvertFrom-Json

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class RestoreDesktop {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);
}
'@

$wall = [string]$b.wallpaper
if ($wall) {
    Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name Wallpaper -Value $wall
    Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name WallpaperStyle -Value ([string]$b.wallpaperStyle)
    Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name TileWallpaper -Value ([string]$b.tileWallpaper)
    [RestoreDesktop]::SystemParametersInfo(20, 0, $wall, 3) | Out-Null
}
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -Name HideIcons -Value ([int]$b.hideIcons) -Type DWord
[RestoreDesktop]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host "restored wallpaper and HideIcons=$($b.hideIcons)"

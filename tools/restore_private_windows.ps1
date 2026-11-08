#requires -Version 7.0
<#
.SYNOPSIS
    Restore windows minimized by hide_private_windows.ps1 and show desktop icons again.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$backupFile = Join-Path $env:USERPROFILE 'AgentCtlDemo\windows-backup.json'
if (-not (Test-Path $backupFile)) { throw "backup not found: $backupFile" }
$b = Get-Content $backupFile -Raw | ConvertFrom-Json

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class RestoreWin32 {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindow(string cls, string win);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string win);
}
'@

function Get-DesktopIconList {
    $progman = [RestoreWin32]::FindWindow('Progman', $null)
    $defView = [IntPtr]::Zero
    if ($progman -ne [IntPtr]::Zero) {
        $defView = [RestoreWin32]::FindWindowEx($progman, [IntPtr]::Zero, 'SHELLDLL_DefView', $null)
    }
    if ($defView -eq [IntPtr]::Zero) {
        $worker = [IntPtr]::Zero
        while ($true) {
            $worker = [RestoreWin32]::FindWindowEx([IntPtr]::Zero, $worker, 'WorkerW', $null)
            if ($worker -eq [IntPtr]::Zero) { break }
            $defView = [RestoreWin32]::FindWindowEx($worker, [IntPtr]::Zero, 'SHELLDLL_DefView', $null)
            if ($defView -ne [IntPtr]::Zero) { break }
        }
    }
    if ($defView -eq [IntPtr]::Zero) { return [IntPtr]::Zero }
    return [RestoreWin32]::FindWindowEx($defView, [IntPtr]::Zero, 'SysListView32', $null)
}

$restored = 0
foreach ($w in @($b.minimized)) {
    if (-not $w) { continue }
    $hwnd = [IntPtr][int64]$w.hwnd
    if ($hwnd -ne [IntPtr]::Zero) {
        [RestoreWin32]::ShowWindow($hwnd, 9) | Out-Null   # SW_RESTORE
        $restored++
    }
}

if ($b.iconsWasVisible) {
    $iconList = Get-DesktopIconList
    if ($iconList -ne [IntPtr]::Zero) {
        [RestoreWin32]::ShowWindow($iconList, 5) | Out-Null  # SW_SHOW
    }
}

Write-Host "restored windows: $restored"
Write-Host "desktop icons visible: $($b.iconsWasVisible)"

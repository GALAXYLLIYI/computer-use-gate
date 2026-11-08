#requires -Version 7.0
<#
.SYNOPSIS
    Minimize every visible app window except the demo windows, and hide desktop icons.
    This is reversible: restore_private_windows.ps1 restores the same windows/icons.
#>
[CmdletBinding()]
param(
    [switch]$KeepAgentCtl
)

$ErrorActionPreference = 'Stop'
$demoDir = Join-Path $env:USERPROFILE 'AgentCtlDemo'
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$backupFile = Join-Path $demoDir 'windows-backup.json'

Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class HideWin32 {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindow(string cls, string win);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string win);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
}
'@

function Get-DesktopIconList {
    $progman = [HideWin32]::FindWindow('Progman', $null)
    $defView = [IntPtr]::Zero
    if ($progman -ne [IntPtr]::Zero) {
        $defView = [HideWin32]::FindWindowEx($progman, [IntPtr]::Zero, 'SHELLDLL_DefView', $null)
    }
    if ($defView -eq [IntPtr]::Zero) {
        $worker = [IntPtr]::Zero
        while ($true) {
            $worker = [HideWin32]::FindWindowEx([IntPtr]::Zero, $worker, 'WorkerW', $null)
            if ($worker -eq [IntPtr]::Zero) { break }
            $defView = [HideWin32]::FindWindowEx($worker, [IntPtr]::Zero, 'SHELLDLL_DefView', $null)
            if ($defView -ne [IntPtr]::Zero) { break }
        }
    }
    if ($defView -eq [IntPtr]::Zero) { return [IntPtr]::Zero }
    return [HideWin32]::FindWindowEx($defView, [IntPtr]::Zero, 'SysListView32', $null)
}

$iconList = Get-DesktopIconList
$iconsWasVisible = $false
if ($iconList -ne [IntPtr]::Zero) {
    $iconsWasVisible = [HideWin32]::IsWindowVisible($iconList)
    [HideWin32]::ShowWindow($iconList, 0) | Out-Null
}

$keepTitles = @('demo.txt', 'Notepad', '计算器', 'Calculator')
$kept = @()
$minimized = @()
foreach ($p in Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle }) {
    $title = [string]$p.MainWindowTitle
    $isDemo = $false
    foreach ($k in $keepTitles) {
        if ($title -like "*$k*") { $isDemo = $true; break }
    }
    if ($isDemo) { $kept += $p; continue }
    if ($KeepAgentCtl -and ($title -match 'AgentCtl|授权|authorize' -or $p.ProcessName -match 'AgentCtl')) {
        $kept += $p; continue
    }
    $minimized += [pscustomobject]@{
        id = $p.Id
        process = $p.ProcessName
        title = $title
        hwnd = [int64]$p.MainWindowHandle
    }
    [HideWin32]::ShowWindow($p.MainWindowHandle, 6) | Out-Null
}

$backup = [ordered]@{
    createdAt = (Get-Date).ToString('o')
    iconsWasVisible = $iconsWasVisible
    minimized = $minimized
}
$backup | ConvertTo-Json -Depth 5 | Set-Content -Path $backupFile -Encoding UTF8

Start-Sleep -Milliseconds 600
$np = Get-Process | Where-Object { $_.MainWindowTitle -match 'demo\.txt|Notepad' } | Select-Object -First 1
if ($np -and $np.MainWindowHandle -ne 0) { [HideWin32]::SetForegroundWindow($np.MainWindowHandle) | Out-Null }

Write-Host "backup: $backupFile"
Write-Host "icons_hidden: $($iconList -ne [IntPtr]::Zero -and $iconsWasVisible)"
Write-Host "kept:"
$kept | Select-Object Id, ProcessName, MainWindowTitle | Format-Table -AutoSize
Write-Host "minimized: $($minimized.Count) window(s)"
$minimized | Select-Object id, process, title | Format-Table -AutoSize

#requires -Version 7.0
<#
.SYNOPSIS
    Prepare a privacy-safe demo desktop with Calculator + Paint only.
    Minimizes every other visible window, hides desktop icons, positions the
    two demo windows, and writes windows-backup.json for restore.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$demoDir = Join-Path $env:USERPROFILE 'AgentCtlDemo'
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null
$backupFile = Join-Path $demoDir 'windows-backup.json'

Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class DemoDesk {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindow(string c, string w);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr FindWindowEx(IntPtr p, IntPtr a, string c, string w);

    public static IntPtr FindIcons() {
        IntPtr progman = FindWindow("Progman", null);
        IntPtr def = FindWindowEx(progman, IntPtr.Zero, "SHELLDLL_DefView", null);
        if (def == IntPtr.Zero) {
            EnumWindows((h, l) => {
                IntPtr d = FindWindowEx(h, IntPtr.Zero, "SHELLDLL_DefView", null);
                if (d != IntPtr.Zero) { def = d; return false; }
                return true;
            }, IntPtr.Zero);
        }
        if (def == IntPtr.Zero) return IntPtr.Zero;
        return FindWindowEx(def, IntPtr.Zero, "SysListView32", null);
    }

    public static bool HideIcons() {
        IntPtr h = FindIcons();
        if (h == IntPtr.Zero) return false;
        return ShowWindow(h, 0);
    }

    public static string MinimizeExcept(long keep1, long keep2) {
        var sb = new StringBuilder();
        EnumWindows((h, l) => {
            if (!IsWindowVisible(h)) return true;
            var c = new StringBuilder(256); GetClassName(h, c, 256);
            string cls = c.ToString();
            if (cls == "Progman" || cls == "Shell_TrayWnd" || cls == "WorkerW") return true;
            long v = h.ToInt64();
            if (v == keep1 || v == keep2) return true;
            ShowWindow(h, 6);
            var t = new StringBuilder(512); GetWindowText(h, t, 512);
            sb.AppendLine(v + "\t" + cls + "\t" + t);
            return true;
        }, IntPtr.Zero);
        return sb.ToString();
    }
}
'@

# Close Settings (not needed for the demo), leave other user apps running.
Get-Process SystemSettings -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process ApplicationFrameHost -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match '设置' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# Start Calculator and Paint fresh.
$calcProc = Start-Process calc.exe -PassThru
Start-Sleep -Seconds 2
$paintProc = Start-Process mspaint.exe -PassThru
Start-Sleep -Seconds 3

# Find their top-level windows. UWP Calculator is hosted by ApplicationFrameHost.
$calc = Get-Process CalculatorApp,ApplicationFrameHost -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match '计算|Calculator' } |
    Select-Object -First 1
if (-not $calc) {
    $calc = Get-Process ApplicationFrameHost -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -notmatch '设置' } |
        Select-Object -First 1
}
$paint = Get-Process mspaint -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1

if (-not $calc) { throw "Calculator window not found" }
if (-not $paint) { throw "Paint window not found" }

$calcHwnd = [int64]$calc.MainWindowHandle
$paintHwnd = [int64]$paint.MainWindowHandle
Write-Host "calc_pid=$($calc.Id) hwnd=$calcHwnd title=$($calc.MainWindowTitle)"
Write-Host "paint_pid=$($paint.Id) hwnd=$paintHwnd title=$($paint.MainWindowTitle)"

$iconsHidden = [DemoDesk]::HideIcons()
$minimizedText = [DemoDesk]::MinimizeExcept($calcHwnd, $paintHwnd)
$minimized = @()
foreach ($line in ($minimizedText -split "`r?`n")) {
    if (-not $line) { continue }
    $p = $line -split "`t"
    if ($p.Count -ge 3) {
        $minimized += [pscustomobject]@{ hwnd = [int64]$p[0]; class = $p[1]; title = $p[2] }
    }
}

$backup = [ordered]@{
    createdAt = (Get-Date).ToString('o')
    iconsWasVisible = [bool]$iconsHidden
    minimized = $minimized
}
$backup | ConvertTo-Json -Depth 5 | Set-Content -Path $backupFile -Encoding UTF8

[DemoDesk]::MoveWindow([IntPtr]$calcHwnd, 400, 320, 450, 600, $true) | Out-Null
[DemoDesk]::MoveWindow([IntPtr]$paintHwnd, 1000, 300, 900, 700, $true) | Out-Null
[DemoDesk]::SetForegroundWindow([IntPtr]$calcHwnd) | Out-Null

Start-Sleep -Milliseconds 700
Write-Host "backup: $backupFile"
Write-Host "icons_hidden: $iconsHidden"
Write-Host "minimized: $($minimized.Count)"
$minimized | Select-Object hwnd, class, title | Format-Table -AutoSize

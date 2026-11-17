@echo off
rem One-click rebuild + swap AgentCtl-fixed (per docs\rebuild-agentctl-20261108.md)
rem Add -SkipBuild to reuse last build output. Add -Yes to skip the swap confirm.
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\rebuild_swap_agentctl.ps1" %*
popd
pause

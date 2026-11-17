@echo off
rem Start AgentCtl scheduler service (background)
python -X utf8 "<仓根>\tools\scheduler.py" --daemon
pause

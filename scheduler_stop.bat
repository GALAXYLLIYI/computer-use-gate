@echo off
rem Stop AgentCtl scheduler service
python -X utf8 "<仓根>\tools\scheduler.py" stop
pause

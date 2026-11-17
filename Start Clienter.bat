@echo off
cd /d "%~dp0"
python Clienter.py
if errorlevel 1 pause

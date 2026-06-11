@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_fill_values_ru_from_library.ps1" %*
exit /b %ERRORLEVEL%

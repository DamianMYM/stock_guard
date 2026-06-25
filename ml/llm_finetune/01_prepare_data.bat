@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

python prepare_data.py
if errorlevel 1 goto :failed

echo.
echo Data preparation completed.
pause
exit /b 0

:failed
echo.
echo Data preparation failed. Review the error above.
pause
exit /b 1

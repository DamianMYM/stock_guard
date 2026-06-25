@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

"%LOCALAPPDATA%\Programs\Ollama\ollama.exe" stop qwen3.5:27b >nul 2>&1
python merge_adapter.py
if errorlevel 1 goto :failed

echo.
echo Merge completed: outputs\stockguard-merged-bf16
pause
exit /b 0

:failed
echo.
echo Merge failed. Review the error above.
pause
exit /b 1

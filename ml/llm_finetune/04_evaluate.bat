@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

"%LOCALAPPDATA%\Programs\Ollama\ollama.exe" stop qwen3.5:27b >nul 2>&1
python evaluate_qlora.py
if errorlevel 1 goto :failed

echo.
echo Evaluation completed. Results: outputs\stockguard-qlora-v1\test_comparison.json
pause
exit /b 0

:failed
echo.
echo Evaluation failed. Review the error above.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

if not exist "models\DeepSeek-R1-Distill-Qwen-7B\model-00001-of-000002.safetensors" goto :missing_model
if not exist "models\DeepSeek-R1-Distill-Qwen-7B\model-00002-of-000002.safetensors" goto :missing_model

python train_qlora.py --smoke-test
if errorlevel 1 goto :failed

echo.
echo Smoke test completed. Adapter: outputs\smoke-test\adapter
pause
exit /b 0

:missing_model
echo The Hugging Face model is incomplete.
echo Expected directory: models\DeepSeek-R1-Distill-Qwen-7B
echo Run the hf download command from README.md first.
pause
exit /b 2

:failed
echo.
echo Smoke test failed. Review the error above.
pause
exit /b 1

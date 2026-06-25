@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

set "HF_ENDPOINT=https://huggingface.co"
set "HF_HOME=%~dp0cache"

echo Hugging Face endpoint: %HF_ENDPOINT%
echo Download directory: %~dp0models\DeepSeek-R1-Distill-Qwen-7B
echo Required download size: about 15.2 GB
echo.

hf download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --local-dir "%~dp0models\DeepSeek-R1-Distill-Qwen-7B"
if errorlevel 1 goto :failed

if not exist "%~dp0models\DeepSeek-R1-Distill-Qwen-7B\model-00001-of-000002.safetensors" goto :incomplete
if not exist "%~dp0models\DeepSeek-R1-Distill-Qwen-7B\model-00002-of-000002.safetensors" goto :incomplete

echo.
echo Model download completed and both weight shards were found.
pause
exit /b 0

:incomplete
echo.
echo The command ended, but one or both model weight shards are missing.
echo Run this script again to resume the download.
pause
exit /b 2

:failed
echo.
echo Model download failed. Review the error above.
pause
exit /b 1

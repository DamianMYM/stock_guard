@echo off
setlocal
cd /d "%~dp0"
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 goto :failed

if not exist "models\DeepSeek-R1-Distill-Qwen-7B\model-00001-of-000002.safetensors" goto :missing_model
if not exist "models\DeepSeek-R1-Distill-Qwen-7B\model-00002-of-000002.safetensors" goto :missing_model

python train_qlora.py ^
  --epochs 1 ^
  --learning-rate 0.0001 ^
  --batch-size 1 ^
  --gradient-accumulation 16 ^
  --max-length 2048 ^
  --lora-rank 16 ^
  --lora-alpha 32 ^
  --output-dir outputs\stockguard-qlora-v1
if errorlevel 1 goto :failed

echo.
echo Training completed. Adapter: outputs\stockguard-qlora-v1\adapter
pause
exit /b 0

:missing_model
echo The Hugging Face model is incomplete. Run 02_smoke_test.bat after the download finishes.
pause
exit /b 2

:failed
echo.
echo Training failed. Review the error above.
pause
exit /b 1

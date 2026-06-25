@echo off
setlocal

call "%USERPROFILE%\anaconda3\Scripts\activate.bat" stock_llm
if errorlevel 1 exit /b 1

cd /d "%~dp0"

set "MERGED_DIR=outputs\stockguard-merged-bf16"
set "BF16_GGUF=outputs\stockguard-ft-bf16.gguf"
set "Q4_GGUF=outputs\stockguard-ft-q4_k_m.gguf"
set "CONVERTER=tools\llama.cpp-b9758\convert_hf_to_gguf.py"
set "QUANTIZER=tools\llama-bin\llama-quantize.exe"

if not exist "%MERGED_DIR%\config.json" (
  echo Missing merged model: %MERGED_DIR%
  exit /b 1
)

python "%CONVERTER%" "%MERGED_DIR%" --outfile "%BF16_GGUF%" --outtype bf16
if errorlevel 1 exit /b 1

"%QUANTIZER%" "%BF16_GGUF%" "%Q4_GGUF%" Q4_K_M
if errorlevel 1 exit /b 1

echo GGUF export completed:
echo   %BF16_GGUF%
echo   %Q4_GGUF%
endlocal

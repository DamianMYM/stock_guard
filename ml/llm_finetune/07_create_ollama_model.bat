@echo off
setlocal

cd /d "%~dp0"

set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA_EXE%" (
  echo Ollama not found at %OLLAMA_EXE%
  exit /b 1
)

set "MODEL_TAG=stockguard-ft-v2:q4"
set "MODELFILE=%~dp0Modelfile.stockguard-ft"

if not exist "%MODELFILE%" (
  echo Missing Modelfile: %MODELFILE%
  exit /b 1
)

"%OLLAMA_EXE%" create %MODEL_TAG% -f "%MODELFILE%"
if errorlevel 1 exit /b 1

echo Created Ollama model: %MODEL_TAG%
endlocal

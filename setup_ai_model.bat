@echo off
setlocal
title 鼓手 AI Model Setup

set "OLLAMA_EXE="
for /f "delims=" %%I in ('where ollama.exe 2^>nul') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "D:\ollama_dir\Ollama\ollama.exe" set "OLLAMA_EXE=D:\ollama_dir\Ollama\ollama.exe"

if not defined OLLAMA_EXE (
  echo Ollama is not installed or is not available in PATH.
  echo Install Ollama first, then run this shortcut again.
  start "" "https://ollama.com/download/windows"
  pause
  exit /b 1
)

echo Preparing the 鼓手 local model. The first download is about 4.7 GB.
"%OLLAMA_EXE%" pull deepseek-r1:7b
if errorlevel 1 goto :failed

"%OLLAMA_EXE%" create stockguard -f "%~dp0Modelfile.stockguard"
if errorlevel 1 goto :failed

echo.
echo 鼓手 AI model is ready.
pause
exit /b 0

:failed
echo.
echo Model setup failed. Check the Ollama service and network connection.
pause
exit /b 1

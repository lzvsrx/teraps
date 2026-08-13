$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Preparando executavel unico do Teraps..."
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name Teraps --icon assets\teraps.ico --add-data "assets\teraps.ico;assets" --add-data "assets\teraps_avatar.png;assets" --hidden-import edge_tts --hidden-import aiohttp --hidden-import speech_recognition --hidden-import sounddevice --hidden-import cffi --hidden-import pyttsx3.drivers --hidden-import pyttsx3.drivers.sapi5 --hidden-import comtypes.stream --exclude-module pandas --exclude-module pyarrow --exclude-module av --exclude-module onnxruntime --exclude-module torch --exclude-module tensorflow --exclude-module transformers --exclude-module huggingface_hub --exclude-module faster_whisper --exclude-module whisper teraps.py

Write-Host ""
Write-Host "Executavel criado em: dist\Teraps.exe"
pause

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Instalando recursos opcionais do Teraps..."
python -m pip install --upgrade pip
python -m pip install pyttsx3 edge-tts psutil SpeechRecognition sounddevice

Write-Host ""
Write-Host "PyAudio e opcional. O Teraps tambem usa sounddevice para capturar o microfone padrao do Windows."
Write-Host "PyAudio pode exigir permissao, wheel compativel, PortAudio ou Build Tools em algumas versoes do Windows/Python."
Write-Host "Tentando instalar PyAudio agora..."
python -m pip install pyaudio

Write-Host ""
Write-Host "Concluido. Se PyAudio falhar, o Teraps usa sounddevice; se os dois falharem, continua por texto e voz sintetizada."
pause

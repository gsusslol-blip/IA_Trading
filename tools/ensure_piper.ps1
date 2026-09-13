# Download Piper CPU binary + Argentine female high-quality voice if missing.
# Official Rhasspy release + piper-voices. Does not fail the whole boot.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$PiperDir = Join-Path $Root "bin\piper"
$PiperExe = Join-Path $PiperDir "piper.exe"
$TtsDir = Join-Path $Root "data\tts"
$Onnx = Join-Path $TtsDir "es_AR-daniela-high.onnx"
$OnnxJson = Join-Path $TtsDir "es_AR-daniela-high.onnx.json"

$PiperZipUrl = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
$VoiceOnnxUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_AR/daniela/high/es_AR-daniela-high.onnx?download=true"
$VoiceJsonUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_AR/daniela/high/es_AR-daniela-high.onnx.json?download=true"

function Get-File([string]$Url, [string]$Dest, [int]$MinBytes) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    $tmp = "$Dest.download"
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 -A "Ilaria/1.5.0" -o $tmp $Url
        if ($LASTEXITCODE -ne 0) { throw "curl failed for $Url" }
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -UserAgent "Ilaria/1.5.0"
    }
    $len = (Get-Item $tmp).Length
    if ($len -lt $MinBytes) {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        throw "Download too small ($len bytes): $Url"
    }
    Move-Item -Force $tmp $Dest
}

function Ensure-PiperBinary {
    if ((Test-Path $PiperExe) -and (Test-Path (Join-Path $PiperDir "espeak-ng-data"))) {
        Write-Host "[Piper] Motor local listo."
        return
    }
    Write-Host "[Piper] Falta el binario. Descargando motor Windows x64..."
    New-Item -ItemType Directory -Force -Path $PiperDir | Out-Null
    $zip = Join-Path $env:TEMP "piper_windows_amd64.zip"
    Get-File $PiperZipUrl $zip 1000000
    $extract = Join-Path $env:TEMP "piper_extract_ilaria"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $found = Get-ChildItem -Path $extract -Recurse -Filter "piper.exe" | Select-Object -First 1
    if (-not $found) { throw "piper.exe not in zip" }
    Copy-Item -Path (Join-Path $found.Directory.FullName "*") -Destination $PiperDir -Recurse -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Host "[Piper] Motor instalado."
}

function Ensure-Voice {
    New-Item -ItemType Directory -Force -Path $TtsDir | Out-Null
    if (-not (Test-Path $Onnx)) {
        Write-Host "[TTS] Falta es_AR-daniela-high.onnx. Bajando voz argentina..."
        Get-File $VoiceOnnxUrl $Onnx 50000000
    }
    if (-not (Test-Path $OnnxJson)) {
        Write-Host "[TTS] Falta el .onnx.json. Bajando config..."
        Get-File $VoiceJsonUrl $OnnxJson 200
    }
    if ((Test-Path $Onnx) -and (Test-Path $OnnxJson)) {
        Write-Host "[TTS] Voz Daniela (es-AR, alta) lista."
    }
}

try {
    Write-Host "=== Voz offline Daniela es-AR ==="
    Ensure-PiperBinary
    Ensure-Voice
    Write-Host "[OK] Piper listo para CPU."
} catch {
    Write-Host "[!] No pude completar Piper: $($_.Exception.Message)"
    Write-Host "[!] El chat arranca igual; la voz queda muda hasta reintentar con red."
}

Piper TTS (Windows amd64)

1. piper_windows_amd64.zip from:
   https://github.com/rhasspy/piper/releases/tag/2023.11.14-2
   Extract so this folder contains piper.exe and espeak-ng-data.

2. Voices in data/tts/ (with matching .onnx.json):
   es_MX-ald-medium.onnx     default, fast CPU
   es_AR-daniela-high.onnx   female Rioplatense (optional PIPER_MODEL)
   There is no es_MX-claude-medium in the official catalog.

Ilaria sends text on STDIN and writes data/tts-*.wav (not data/audio/reply_*.wav).

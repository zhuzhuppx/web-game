"""语音识别服务 - 本地 Whisper (faster-whisper)"""
import os, sys, time
import tempfile
from flask import Flask, request, jsonify
from faster_whisper import WhisperModel

app = Flask(__name__)

model_size = os.environ.get("WHISPER_MODEL", "base")
cache_dir = os.environ.get("WHISPER_CACHE", None)

# 检测 CUDA（faster-whisper 用 CTranslate2，不用 torch）
try:
    import ctranslate2
    device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
except:
    device = "cpu"
compute = "float16" if device == "cuda" else "int8"

print(f"Loading {model_size} on {device}...", flush=True)
model = WhisperModel(model_size, device=device, compute_type=compute,
                     download_root=cache_dir, local_files_only=True)
print("Model ready.", flush=True)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    t0 = time.time()
    # 支持 multipart 上传和原始二进制流
    if request.files and "audio" in request.files:
        audio = request.files["audio"]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio.save(f.name)
            tmp_path = f.name
    elif request.data:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(request.data)
            tmp_path = f.name
    else:
        return jsonify({"error": "no audio data"}), 400
    try:
        size = os.path.getsize(tmp_path)
        print(f"[{time.strftime('%H:%M:%S')}] audio: {size}B", flush=True)
        segments, info = model.transcribe(tmp_path, language="zh", beam_size=5, vad_filter=True)
        text = " ".join([s.text for s in segments])
        elapsed = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] result: '{text}' ({elapsed:.1f}s)", flush=True)
        return jsonify({"text": text.strip() or ""})
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] error: {e}", flush=True)
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8766)

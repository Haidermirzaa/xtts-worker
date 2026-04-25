"""
RunPod Serverless handler for XTTS v2 voice cloning.
────────────────────────────────────────────────────
How this works:
  1. RunPod calls `handler(job)` for each request.
  2. `job["input"]` contains: text, language, speed, speaker_audio_b64, secret
  3. We clone the voice using XTTS v2 and return the audio as base64.

The XTTS model is loaded ONCE at container startup (module-level), so
subsequent requests on the same worker are fast. Cold start = ~30s.
Warm request = ~3-10s depending on text length.

Protocol note:
  The main app (voice_clone_engine.py) uses a multipart-form HTTP call
  for normal HTTPS deployments. For RunPod Serverless it switches to
  their JSON-over-HTTPS format via the `RUNPOD_ENDPOINT` env var.
"""

import os
import io
import base64
import hmac
import hashlib
import tempfile
import traceback

import torch
import runpod
from TTS.api import TTS

# ─────────────────────────────────────────────────────────────
# Model load (happens once when the container boots)
# ─────────────────────────────────────────────────────────────
print("[XTTS] Loading model...")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[XTTS] Device: {DEVICE}")

# XTTS v2 — latest multilingual voice cloning model from Coqui
# Supports 17 languages including Hindi (our fallback for Urdu).
# About 1.9 GB on disk, ~4 GB VRAM.
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# Accept Coqui's TOS non-interactively (required for XTTS v2 weights)
os.environ["COQUI_TOS_AGREED"] = "1"

tts = TTS(MODEL_NAME).to(DEVICE)
print("[XTTS] Model loaded. Ready for requests.")

# Languages XTTS v2 natively supports. Urdu is NOT in this list —
# we remap it to Hindi since they're mutually intelligible spoken.
XTTS_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr",
    "ru", "nl", "cs", "ar", "zh", "hu", "ko", "ja", "hi",
}

# Shared secret — must match XTTS_WORKER_SECRET in the main app's env vars.
# Empty string means no auth (NOT recommended — always set a secret).
WORKER_SECRET = os.environ.get("WORKER_SECRET", "").strip()


def _verify_secret(provided: str) -> bool:
    """Constant-time comparison to avoid timing attacks."""
    if not WORKER_SECRET:
        # If no secret is configured, reject anyway — forcing a secret
        # prevents accidental exposure of a free GPU to the internet.
        return False
    return hmac.compare_digest(provided or "", WORKER_SECRET)


def _resolve_language(lang: str) -> str:
    """Map a user-provided language code to what XTTS actually supports."""
    base = (lang or "en").split("-")[0].lower()
    if base == "ur":
        return "hi"   # Urdu → Hindi fallback
    if base in XTTS_LANGS:
        return base
    return "en"


def _clamp_speed(speed) -> float:
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return 1.0
    # XTTS gets weird outside this range
    return max(0.5, min(2.0, s))


def handler(job):
    """
    Main entry point called by RunPod for every request.
    Input schema (job["input"]):
        {
            "secret":             <str>  required, shared secret
            "text":               <str>  required, text to speak
            "language":           <str>  required, e.g. "en", "hi", "ur"
            "speed":              <float> optional, default 1.0
            "speaker_audio_b64":  <str>  required, base64-encoded audio sample
        }
    Returns:
        { "audio_b64": <str>, "format": "wav", "sample_rate": 24000 }
        or { "error": <str> } on failure.
    """
    try:
        inp = job.get("input") or {}

        # 1. Auth check
        if not _verify_secret(inp.get("secret", "")):
            return {"error": "Unauthorized — invalid or missing secret."}

        # 2. Input validation
        text = (inp.get("text") or "").strip()
        if not text:
            return {"error": "Missing 'text'."}
        if len(text) > 50000:
            # ~50 min of audio — safety cap. Main app enforces plan limits.
            return {"error": "Text too long (>50,000 chars)."}

        language = _resolve_language(inp.get("language", "en"))
        speed    = _clamp_speed(inp.get("speed", 1.0))

        speaker_b64 = inp.get("speaker_audio_b64") or ""
        if not speaker_b64:
            return {"error": "Missing 'speaker_audio_b64'."}

        # Decode the user's voice sample to a temporary file on disk.
        # XTTS wants a file path, not bytes.
        try:
            speaker_bytes = base64.b64decode(speaker_b64, validate=False)
        except Exception as e:
            return {"error": f"Invalid base64 audio: {e}"}

        if len(speaker_bytes) < 1000:
            return {"error": "Speaker audio too short or empty."}
        if len(speaker_bytes) > 20 * 1024 * 1024:
            return {"error": "Speaker audio too large (>20 MB)."}

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav", dir="/tmp"
        ) as speaker_file:
            speaker_file.write(speaker_bytes)
            speaker_path = speaker_file.name

        # 3. Generate
        output_path = tempfile.mktemp(suffix=".wav", dir="/tmp")

        try:
            tts.tts_to_file(
                text=text,
                speaker_wav=speaker_path,
                language=language,
                file_path=output_path,
                speed=speed,
            )
        finally:
            # Always clean up the speaker sample — we don't keep copies
            try: os.unlink(speaker_path)
            except Exception: pass

        # 4. Read back + return as base64 (RunPod's protocol is JSON)
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        try: os.unlink(output_path)
        except Exception: pass

        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        return {
            "audio_b64":   audio_b64,
            "format":      "wav",
            "sample_rate": 24000,
            "language_used": language,
            "chars":       len(text),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[XTTS ERROR] {e}\n{tb}")
        return {"error": f"Worker error: {str(e)[:300]}"}


# RunPod entry point
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
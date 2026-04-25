# RunPod-compatible base image with CUDA + PyTorch preinstalled.
# Saves ~2 GB of download vs building from python:3.10.
FROM runpod/base:0.6.2-cuda12.1.0

# Agree to Coqui TTS license non-interactively.
# Without this, the container hangs on first run.
ENV COQUI_TOS_AGREED=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/runpod-volume/huggingface
ENV COQUI_TOS_AGREED=1
# Prevent Coqui from re-checking the model every cold start
ENV TTS_HOME=/runpod-volume/tts

WORKDIR /app

# Copy requirements first for Docker layer caching — if requirements
# don't change, this layer is cached on subsequent builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the XTTS v2 model into the image so cold starts don't
# waste 30+ seconds fetching 1.9 GB of weights from HuggingFace every time.
RUN python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')"

# Copy the handler last
COPY handler.py .

# Entry point — RunPod calls this to start the worker loop
CMD ["python", "-u", "handler.py"]
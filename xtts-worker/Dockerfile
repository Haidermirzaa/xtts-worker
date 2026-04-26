FROM runpod/base:0.6.2-cuda12.1.0

ENV COQUI_TOS_AGREED=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/runpod-volume/huggingface
ENV TTS_HOME=/runpod-volume/tts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')"

COPY handler.py .

CMD ["python", "-u", "handler.py"]

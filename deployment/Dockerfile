# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim-trixie
FROM ${PYTHON_IMAGE}
ARG TARGETARCH
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/r1
COPY deployment/requirements.txt /opt/r1/deployment/requirements.txt
RUN pip install --no-cache-dir -r /opt/r1/deployment/requirements.txt
COPY deployment/assets.py deployment/configuration.py deployment/gateway_entry.py deployment/entrypoint.py deployment/healthcheck.py /opt/r1/deployment/
COPY asr/sources.json asr/music-hotwords.txt /opt/r1/asr/
RUN python /opt/r1/deployment/assets.py runtime --architecture "${TARGETARCH}" --destination /opt/sherpa \
    && LD_LIBRARY_PATH=/opt/sherpa/lib /opt/sherpa/bin/sherpa-onnx-online-websocket-server --help >/dev/null 2>&1
COPY gateway/voice_gateway.py gateway/gateway_config.py gateway/event_log.py gateway/gateway.example.json gateway/music-commands.json /opt/r1/gateway/
COPY gateway/audio_transport.py gateway/tts_cache.py gateway/intent_rules.py gateway/intent-rules.json /opt/r1/gateway/
COPY gateway/command-pause-16k.wav /opt/r1/gateway/
RUN mkdir -p /data /models && chown 1000:1000 /data /models
USER 1000:1000
EXPOSE 16066 16068
HEALTHCHECK --interval=15s --timeout=8s --start-period=120s --retries=3 \
    CMD ["python", "/opt/r1/deployment/healthcheck.py"]
ENTRYPOINT ["python", "/opt/r1/deployment/entrypoint.py"]
CMD ["serve"]

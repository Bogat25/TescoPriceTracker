FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models

WORKDIR /app

# CPU-only torch: the CUDA build would add several GB for nothing on this host.
RUN pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --system --no-create-home app && mkdir /models && chown app /models
USER app

# Bake the model in at a fixed revision: no download at start-up, and the
# same weights every build (vectors stay comparable across deploys).
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ARG EMBEDDING_MODEL_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('${EMBEDDING_MODEL}', revision='${EMBEDDING_MODEL_REVISION}', allow_patterns=['*.json', '*.safetensors', 'sentencepiece.bpe.model', '1_Pooling/*'])" \
 && python -c "from huggingface_hub import scan_cache_dir; print(scan_cache_dir().size_on_disk_str)"

ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_MODEL_REVISION=${EMBEDDING_MODEL_REVISION} \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY app.py logging_setup.py ./

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

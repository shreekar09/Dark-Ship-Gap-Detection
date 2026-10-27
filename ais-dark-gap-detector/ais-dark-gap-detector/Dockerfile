FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    MPLCONFIGDIR=/tmp/mpl \
    DUCKDB_TEMP_DIR=/tmp/duckdb_tmp

WORKDIR /app

# Dependencies first so this layer is cached when only code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY run_pipeline.py ./
COPY src ./src
COPY tests ./tests

# Data and results live on mounted volumes, not in the image
RUN mkdir -p data/raw data/ref outputs /tmp/mpl /tmp/duckdb_tmp && chmod -R 777 /tmp/mpl /tmp/duckdb_tmp data outputs

ENTRYPOINT ["python", "run_pipeline.py"]
CMD ["--help"]

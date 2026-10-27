# Interactive DuckDB CLI for exploring the pipeline's Parquet/CSV outputs and the raw NOAA files.
# Version is pinned to match the duckdb Python package in requirements.txt.
FROM debian:bookworm-slim
ARG TARGETARCH
ARG DUCKDB_VERSION=v1.4.1
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/duckdb.zip \
       "https://github.com/duckdb/duckdb/releases/download/${DUCKDB_VERSION}/duckdb_cli-linux-${TARGETARCH}.zip" \
    && unzip /tmp/duckdb.zip -d /usr/local/bin && chmod +x /usr/local/bin/duckdb && rm /tmp/duckdb.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y
WORKDIR /work
ENTRYPOINT ["duckdb"]

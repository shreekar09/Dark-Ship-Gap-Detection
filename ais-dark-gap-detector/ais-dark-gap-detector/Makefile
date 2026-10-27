.PHONY: build test download run shell sql
DAY ?= 2023-01-15
DAYS ?= 2

build:
	docker compose build

test: build
	docker compose run --rm test

download: build        ## make download DAY=2023-01-15 DAYS=2
	docker compose run --rm download $(DAY) $(DAYS)

run: build             ## process compressed CSVs in data/raw
	docker compose run --rm pipeline --input "data/raw/*.csv.zst"

shell: build
	docker compose run --rm --entrypoint bash pipeline

sql: build             ## DuckDB shell over data/ and outputs/
	docker compose run --rm duckdb -init sql/explore.sql

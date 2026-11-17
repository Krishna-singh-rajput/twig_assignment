.PHONY: setup run evaluate test export clean docker-build docker-run

setup:
	pip install -r requirements.txt

run:
	python -m pipeline run

evaluate:
	python -m pipeline evaluate

test:
	python -m pytest -v

export:
	python -m pipeline export

stats:
	python -m pipeline stats

clean:
	rm -rf data/*.db data/*.duckdb output/* __pycache__ .pytest_cache .coverage

docker-build:
	docker compose build

docker-run:
	docker compose up

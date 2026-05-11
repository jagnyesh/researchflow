.PHONY: run docker-up test

run:
	uvicorn app.main:app --reload --port 8000

docker-up:
	docker-compose -f config/docker-compose.yml up --build

test:
	pytest -q

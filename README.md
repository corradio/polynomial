# Polynomial

## Installing dependencies
```sh
poetry install
pre-commit install
```

## Start database
```sh
docker-compose up pgdb
```

## Running server
```sh
poetry run python manage.py runserver
```

## Type check
```sh
poetry run mypy .
```

## Format code
```sh
poetry run black .
```

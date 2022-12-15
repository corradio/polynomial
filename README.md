# Polynomial

## Installing dependencies
```sh
poetry install
pre-commit install
```


## Database

### Start database
```sh
docker-compose up pgdb
```

### Run migrations
```sh
poetry run python manage.py migrate
```

### Create a new migration once the model has been changed
```sh
poetry run python manage.py makemigrations
```

### Create a new admin user
```sh
poetry run python manage.py createsuperuser
```

### Restart from scratch
```sh
docker-compose stop pgdb
docker-compose rm -v -f pgdb
```


## Run server
```sh
poetry run python manage.py runserver
```


## Debug stuff
```sh
poetry run python manage.py shell
```


## Code quality

### Type check
```sh
poetry run mypy .
```

### Format code
```sh
poetry run black .
```

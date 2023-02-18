# Polynomial

## Installing dependencies
```sh
poetry install
yarn
pre-commit install
```


## Database

### Start database
```sh
docker-compose up pgdb
```

## Initiate db with migrations
```sh
make initdb
```

### Seed some data
```sh
make seed
```

### Run migrations
```sh
poetry run python manage.py migrate
```

### Create a new migration once the model has been changed
```sh
poetry run python manage.py makemigrations
```

### Reset db (if something goes wrong with migrations)
```sh
make resetdb
```


## Run everything (server + javascript/css watcher + db + cache)
```sh
make rundev
```


## Debug stuff
```sh
make shell
```


## Code quality

### Type check
```sh
make typecheck
```

### Format code
```sh
make format
```

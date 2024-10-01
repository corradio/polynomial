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

### Initiate db with migrations
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

Now you can login with `admin@admin.com` and `test` as password. Afterwards, go into the database and set the account in `account_emailaddress` to "verified" true.

## Run all the tests
```sh
make test
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

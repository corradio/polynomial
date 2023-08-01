MANAGE = poetry run python manage.py

seed:
	DJANGO_SUPERUSER_USERNAME=admin \
	DJANGO_SUPERUSER_PASSWORD=test \
	DJANGO_SUPERUSER_EMAIL="admin@admin.com" \
	$(MANAGE) createsuperuser --noinput || true
	$(MANAGE) shell < seed.py

cleardb:
	docker-compose stop pgdb
	docker-compose rm -v -f pgdb
	docker-compose up -d pgdb
	rm -rf mainapp/migrations/* && git checkout mainapp/migrations
	$(MANAGE) makemigrations

initdb:
	$(MANAGE) migrate

resetdb: cleardb initdb seed

shell:
	$(MANAGE) shell

runserver:
	OAUTHLIB_INSECURE_TRANSPORT=1 DEBUG=1 $(MANAGE) runserver

rundev:
	PYTHONUNBUFFERED=true poetry run honcho start

format:
	poetry run black .
	poetry run isort .

typecheck:
	poetry run mypy .

test:
	$(MANAGE) test

deploy:
	poetry run fly deploy

# Celery
runworker:
	DEBUG=1 poetry run celery -A config worker -l DEBUG

runbeat:
	DEBUG=1 poetry run celery -A config beat -l INFO

runtasks:
	DEBUG=1 poetry run celery -A config call mainapp.tasks.collect_all_latest_task

notebook:
	$(MANAGE) shell_plus --notebook

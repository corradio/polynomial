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

runserver:
	OAUTHLIB_INSECURE_TRANSPORT=1 $(MANAGE) runserver

format:
	poetry run black .
	poetry run isort .

typecheck:
	poetry run mypy .

deploy:
	poetry run fly deploy

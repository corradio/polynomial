MANAGE = poetry run python manage.py

seed:
	DJANGO_SUPERUSER_USERNAME=admin \
	DJANGO_SUPERUSER_PASSWORD=test \
	DJANGO_SUPERUSER_EMAIL="admin@admin.com" \
	$(MANAGE) createsuperuser --noinput || true
	$(MANAGE) shell -c "from mainapp.models import Metric,User; Metric(name='test_metric', user_id=User.objects.get(username='admin').id).save()"
	$(MANAGE) shell -c "from mainapp.models import IntegrationInstance,Metric; IntegrationInstance(name='plausible', metric_id=Metric.objects.get(name='test_metric').id).save()"

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
	$(MANAGE) runserver

shell:
	$(MANAGE) shell

format:
	poetry run black .
	poetry run isort .

typecheck:
	poetry run mypy .
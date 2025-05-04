import posthog
from django.apps import AppConfig
from environs import Env

env = Env()
env.read_env()  # read .env file, if it exists


class MainappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mainapp"

    def ready(self):
        import mainapp.signals  # no qa

        posthog.api_key = env.str("POSTHOG_API_KEY", default="")
        posthog.host = "https://eu.i.posthog.com"

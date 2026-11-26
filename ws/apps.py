from django.apps import AppConfig
from django.db.models.signals import post_migrate


class WsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ws"
    verbose_name = "Gestionale"

    def ready(self):
        from .ruoli import imposta_ruoli

        post_migrate.connect(imposta_ruoli, sender=self)

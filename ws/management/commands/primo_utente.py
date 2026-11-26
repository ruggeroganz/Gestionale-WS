import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea l'utente amministratore iniziale, solo se non esiste ancora nessun utente."

    def handle(self, *args, **opts):
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write("Utenti già presenti: nessuna modifica.")
            return
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            self.stdout.write(self.style.WARNING("ADMIN_PASSWORD non impostata: nessun utente creato."))
            return
        User.objects.create_superuser(os.environ.get("ADMIN_USERNAME", "admin"), password=password)
        self.stdout.write(self.style.SUCCESS("Creato l'utente amministratore iniziale."))

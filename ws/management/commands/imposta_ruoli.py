from django.core.management.base import BaseCommand

from ws.ruoli import RUOLI, imposta_ruoli


class Command(BaseCommand):
    help = "Riporta i permessi dei tre ruoli aziendali ai valori iniziali."

    def handle(self, *args, **opts):
        imposta_ruoli(ripristina=True)
        self.stdout.write(self.style.SUCCESS("Permessi ripristinati per: " + ", ".join(RUOLI)))

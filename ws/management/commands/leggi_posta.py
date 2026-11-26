"""Scarica le mail non lette dalla casella dell'assistente (IMAP) e le analizza.

Variabili d'ambiente: POSTA_IMAP_HOST, POSTA_IMAP_UTENTE, POSTA_IMAP_PASSWORD,
facoltative POSTA_IMAP_CARTELLA (INBOX) e POSTA_IMAP_PORTA (993).
Da eseguire a intervalli regolari (es. ogni 10 minuti).
"""
import imaplib
import os

from django.core.management.base import BaseCommand, CommandError

from ws import assistente
from ws.views import crea_messaggio


class Command(BaseCommand):
    help = "Scarica e analizza le mail non lette della casella dell'assistente."

    def handle(self, *args, **opts):
        host, utente, password = (os.environ.get(k) for k in ("POSTA_IMAP_HOST", "POSTA_IMAP_UTENTE", "POSTA_IMAP_PASSWORD"))
        if not (host and utente and password):
            raise CommandError("Casella non configurata: servono POSTA_IMAP_HOST, POSTA_IMAP_UTENTE e POSTA_IMAP_PASSWORD.")
        casella = imaplib.IMAP4_SSL(host, int(os.environ.get("POSTA_IMAP_PORTA", "993")))
        try:
            casella.login(utente, password)
            casella.select(os.environ.get("POSTA_IMAP_CARTELLA", "INBOX"))
            _, dati = casella.search(None, "UNSEEN")
            nuove = 0
            for numero in dati[0].split():
                _, parti = casella.fetch(numero, "(RFC822)")  # la lettura segna la mail come letta
                try:
                    m = crea_messaggio(parti[0][1])
                except assistente.AssistenteError as e:
                    self.stderr.write(f"Mail {numero.decode()} saltata: {e}")
                    continue
                nuove += 1
                if assistente.configurato():
                    try:
                        assistente.elabora(m)
                    except assistente.AssistenteError as e:
                        self.stderr.write(f"«{m.oggetto}» non analizzata: {e}")
        finally:
            try:
                casella.logout()
            except imaplib.IMAP4.error:
                pass
        self.stdout.write(self.style.SUCCESS(f"{nuove} nuove mail."))

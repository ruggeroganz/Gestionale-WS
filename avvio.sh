#!/bin/sh
# Avvio in produzione: aggiorna il database, crea il primo utente se serve, avvia il server.
set -e
python manage.py migrate --noinput
python manage.py primo_utente
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --access-logfile -

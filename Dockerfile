FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# librerie di sistema per la generazione dei PDF
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# i file statici non dipendono dal database: si preparano in fase di build
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["./avvio.sh"]

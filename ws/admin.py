from django.apps import apps
from django.contrib import admin

admin.site.site_header = "Gestionale WS · amministrazione"
admin.site.site_title = "Gestionale WS"

for model in apps.get_app_config("ws").get_models():
    admin.site.register(model)

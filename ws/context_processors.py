from django.conf import settings


def azienda(request):
    return {"NOME_AZIENDA": settings.NOME_AZIENDA}

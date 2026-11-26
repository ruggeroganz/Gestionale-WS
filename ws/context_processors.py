from .models import Azienda


def azienda(request):
    return {"NOME_AZIENDA": Azienda.corrente().ragione_sociale, "base_template": "ws/base.html"}

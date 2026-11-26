from .accessi import sezioni_nascoste
from .models import Azienda


def azienda(request):
    return {"NOME_AZIENDA": Azienda.corrente().ragione_sociale, "base_template": "ws/base.html", "nascoste": sezioni_nascoste(request.user) if hasattr(request, "user") else set()}

from decimal import Decimal

from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def prezzo(valore):
    """Prezzo unitario: tre decimali per i centesimi di euro, due (con separatore delle migliaia) dai 100 € in su."""
    if valore in (None, ""):
        return ""
    return floatformat(valore, "2g" if abs(Decimal(valore)) >= 100 else 3)


def lingua_di(contesto):
    """Lingua dei documenti del cliente a cui è intestato il documento in pagina."""
    if contesto.get("sp") is not None:
        return "en"  # packing list e dichiarazione merci pericolose sono sempre in inglese
    for nome in ("d", "o", "q"):
        obj = contesto.get(nome)
        if obj is None:
            continue
        cliente = getattr(obj, "cliente", None) or getattr(getattr(obj, "progetto", None), "cliente", None)
        if cliente is not None:
            return cliente.lingua_documenti
    return "it"


@register.simple_tag(takes_context=True)
def t(context, italiano, inglese):
    """Testo nella lingua dei documenti del cliente: {% t "Quantità" "Quantity" %}."""
    return inglese if lingua_di(context) == "en" else italiano

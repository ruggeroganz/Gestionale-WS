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

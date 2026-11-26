"""Ruoli aziendali e cosa può inserire o modificare ciascuno.

Tutti gli utenti autenticati possono consultare ogni pagina. I permessi di
scrittura sono i normali permessi di Django sui gruppi: quelli qui sotto sono
i valori iniziali, poi modificabili dal pannello di amministrazione.
"""

COMMERCIALE = "Commerciale"
CUSTOMER = "Customer service e acquisti"
AMMINISTRAZIONE = "Amministrazione"

_SVILUPPO = ["progetto", "evento", "quotazione", "rigaquotazione", "campionatura"]
_ANAGRAFICA_CLIENTI = ["cliente", "contatto"]
_TECNICO = ["formula", "versioneformula", "teststabilita", "componente", "artwork", "packaging", "prodotto", "rigadistinta"]
_ORDINI = ["ordinecliente", "rigaordine"]
_LOGISTICA = ["movimentopackaging", "ordineacquisto", "rigaacquisto", "ddt", "rigaddt"]
_FATTURE = ["prefattura", "rigaprefattura"]

RUOLI = {
    COMMERCIALE: _ANAGRAFICA_CLIENTI + _SVILUPPO + _ORDINI,
    CUSTOMER: _ANAGRAFICA_CLIENTI + ["produttore"] + _SVILUPPO + _TECNICO + _ORDINI + _LOGISTICA,
    AMMINISTRAZIONE: _ANAGRAFICA_CLIENTI + ["produttore", "azienda", "evento", "ordineacquisto", "rigaacquisto"] + _FATTURE,
}


def imposta_ruoli(ripristina=False, **kwargs):
    """Crea i gruppi; assegna i permessi iniziali solo ai gruppi nuovi (o a tutti con ripristina=True)."""
    from django.contrib.auth.models import Group, Permission

    for nome, modelli in RUOLI.items():
        gruppo, creato = Group.objects.get_or_create(name=nome)
        if creato or ripristina:
            gruppo.permissions.set(
                Permission.objects.filter(content_type__app_label="ws", content_type__model__in=modelli)
            )


def puo(utente, azione, modello):
    """azione: add, change o delete."""
    return utente.has_perm(f"ws.{azione}_{modello._meta.model_name}")

"""Ruoli aziendali e cosa può inserire o modificare ciascuno.

Tutti gli utenti autenticati possono consultare ogni pagina. I permessi di
scrittura sono i normali permessi di Django sui gruppi: quelli qui sotto sono
i valori predefiniti. Dal pannello di amministrazione se ne possono aggiungere
altri; quelli predefiniti vengono riassegnati a ogni aggiornamento.
"""

COMMERCIALE = "Commerciale"
CUSTOMER = "Customer service e acquisti"
AMMINISTRAZIONE = "Amministrazione"

_SVILUPPO = ["progetto", "evento", "quotazione", "rigaquotazione", "campionatura", "vocelistino", "promemoria", "brief"]
_ANAGRAFICA_CLIENTI = ["cliente", "contatto"]
_TECNICO = ["formula", "versioneformula", "teststabilita", "componente", "artwork", "packaging", "prodotto", "rigadistinta"]
_ORDINI = ["ordinecliente", "rigaordine"]
_POSTA = ["messaggioposta", "allegatoposta"]
_LOGISTICA = ["movimentopackaging", "ordineacquisto", "rigaacquisto", "ddt", "rigaddt", "spedizione", "collo"]
_FATTURE = ["prefattura", "rigaprefattura"]

RUOLI = {
    COMMERCIALE: _ANAGRAFICA_CLIENTI + _SVILUPPO + _ORDINI,
    CUSTOMER: _ANAGRAFICA_CLIENTI + ["produttore"] + _SVILUPPO + _TECNICO + _ORDINI + _LOGISTICA + _POSTA,
    AMMINISTRAZIONE: _ANAGRAFICA_CLIENTI + ["produttore", "azienda", "evento", "promemoria", "ordineacquisto", "rigaacquisto"] + _FATTURE + _POSTA,
}


def imposta_ruoli(ripristina=False, **kwargs):
    """Crea i gruppi e aggiunge i permessi predefiniti mancanti (così le funzioni nuove sono subito usabili).

    Con ripristina=True i permessi tornano esattamente a quelli predefiniti.
    """
    from django.contrib.auth.models import Group, Permission

    for nome, modelli in RUOLI.items():
        gruppo, creato = Group.objects.get_or_create(name=nome)
        permessi = Permission.objects.filter(content_type__app_label="ws", content_type__model__in=modelli)
        if ripristina:
            gruppo.permissions.set(permessi)
        else:
            gruppo.permissions.add(*permessi)


def puo(utente, azione, modello):
    """azione: add, change o delete."""
    return utente.has_perm(f"ws.{azione}_{modello._meta.model_name}")

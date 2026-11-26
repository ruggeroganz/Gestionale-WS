"""Chi può vedere cosa.

- Utenti del produttore: vedono solo l'area riservata, con i progetti del loro
  produttore e senza prezzi né clienti. Ogni altra pagina li riporta lì.
- Utenti interni: il gestore può nascondere a ciascuno intere sezioni.
"""
from django.contrib import messages
from django.shortcuts import redirect

# chiave -> (nome mostrato, nomi delle pagine che ne fanno parte)
SEZIONI = {
    "progetti": ("Progetti, brief e quotazioni", ("progetti", "progetto", "progetto_avanza", "progetto_arretra", "progetto_nota", "brief", "brief_nuovo", "brief_scarica", "quotazione_stampa", "quotazione_duplica")),
    "clienti": ("Clienti", ("clienti", "cliente")),
    "produttori": ("Produttori", ("produttori",)),
    "formule": ("Formule", ("formule",)),
    "listino": ("Listino prezzi", ("listino", "listino_salva_riga", "listino_usa")),
    "prodotti": ("Prodotti, distinte e packaging", ("prodotti", "prodotto", "prodotto_riordino", "catalogo")),
    "magazzino": ("Magazzino packaging", ("magazzino",)),
    "ordini": ("Ordini clienti", ("ordini", "ordine", "ordine_stampa", "ordine_registra_packaging", "ordine_genera_acquisto", "ordine_genera_ddt", "ordine_genera_prefattura", "ordine_genera_spedizione")),
    "acquisti": ("Ordini ai produttori", ("acquisti", "acquisto")),
    "spedizioni": ("DDT e spedizioni", ("ddt_elenco", "ddt", "spedizioni", "spedizione")),
    "posta": ("Posta e assistente", ("posta", "messaggio", "posta_carica", "messaggio_analizza", "messaggio_applica", "messaggio_stato")),
    "fatture": ("Pre-fatture", ("prefatture", "prefattura", "prefattura_esporta")),
}  # fmt: skip
PAGINA_SEZIONE = {pagina: chiave for chiave, (_, pagine) in SEZIONI.items() for pagina in pagine}
# modelli del form generico e documenti PDF -> sezione
MODELLO_SEZIONE = {
    "cliente": "clienti", "contatto": "clienti", "produttore": "produttori", "progetto": "progetti", "formula": "formule",
    "versioneformula": "formule", "campionatura": "progetti", "stabilita": "progetti", "quotazione": "progetti",
    "rigaquotazione": "progetti", "artwork": "progetti", "promemoria": None, "componente": "prodotti", "packaging": "prodotti",
    "prodotto": "prodotti", "rigadistinta": "prodotti", "movimento": "magazzino", "ordine": "ordini", "rigaordine": "ordini",
    "acquisto": "acquisti", "rigaacquisto": "acquisti", "ddt": "spedizioni", "rigaddt": "spedizioni", "spedizione": "spedizioni",
    "collo": "spedizioni", "prefattura": "fatture", "rigaprefattura": "fatture", "vocelistino": "listino", "azienda": None,
}  # fmt: skip
PDF_SEZIONE = {"offerta": "progetti", "conferma": "ordini", "ddt": "spedizioni", "prefattura": "fatture", "acquisto": "acquisti", "packing": "spedizioni", "multimodale": "spedizioni"}
PAGINE_PRODUTTORE = {"portale", "portale_progetto", "portale_file", "portale_tds", "logout", "password", "password_fatto", "login"}


def profilo_di(utente):
    if not utente.is_authenticated:
        return None
    from .models import Profilo

    try:
        return utente.profilo
    except Profilo.DoesNotExist:
        return None


def sezioni_nascoste(utente):
    p = profilo_di(utente)
    return set(p.sezioni_nascoste or []) if p else set()


def sezione_della_pagina(nome, parametri):
    if nome in ("nuovo", "modifica", "elimina"):
        return MODELLO_SEZIONE.get(parametri.get("modello"))
    if nome == "pdf":
        return PDF_SEZIONE.get(parametri.get("tipo"))
    return PAGINA_SEZIONE.get(nome)


class AccessiMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, vista, argomenti, parametri):
        utente = getattr(request, "user", None)
        if utente is None or not utente.is_authenticated or request.resolver_match is None:
            return None
        nome = request.resolver_match.url_name
        profilo = profilo_di(utente)
        if profilo is not None and profilo.produttore_id:
            # utente esterno: solo l'area riservata (niente amministrazione, niente file diretti)
            if nome in PAGINE_PRODUTTORE and not request.resolver_match.namespace:
                return None
            return redirect("portale")
        if nome and nome.startswith("portale"):
            return redirect("dashboard")
        if request.resolver_match.namespace == "admin":
            return None
        sezione = sezione_della_pagina(nome, parametri)
        if sezione and profilo is not None and sezione in (profilo.sezioni_nascoste or []):
            messages.error(request, f"Non hai accesso alla sezione «{SEZIONI[sezione][0]}».")
            return redirect("dashboard")
        return None

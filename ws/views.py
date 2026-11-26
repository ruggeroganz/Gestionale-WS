from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, ProtectedError, Q
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import documenti, flusso
from .accessi import SEZIONI, profilo_di, sezioni_nascoste
from .ruoli import RUOLI, puo
from .models import (
    DDT,
    Artwork,
    Azienda,
    Brief,
    Collo,
    Campionatura,
    Cliente,
    Componente,
    Contatto,
    Evento,
    Formula,
    MovimentoPackaging,
    OrdineAcquisto,
    OrdineCliente,
    Packaging,
    MessaggioPosta,
    PreFattura,
    Profilo,
    Promemoria,
    Prodotto,
    Produttore,
    Progetto,
    Quotazione,
    RigaAcquisto,
    RigaDDT,
    RigaDistinta,
    RigaOrdine,
    RigaPreFattura,
    RigaQuotazione,
    Spedizione,
    TestStabilita,
    VersioneFormula,
    VoceListino,
)

# Modelli modificabili dall'interfaccia con il form generico: nome -> (modello, campi)
CRUD = {
    "cliente": (Cliente, ["ragione_sociale", "tipo", "stato", "partita_iva", "codice_fiscale", "indirizzo", "cap", "comune", "provincia", "codice_paese", "paese", "codice_sdi", "pec", "pagamento", "lingua_documenti", "email", "telefono", "commerciale", "note"]),
    "contatto": (Contatto, ["cliente", "nome", "ruolo", "email", "telefono"]),
    "produttore": (Produttore, ["nome", "paese", "indirizzo", "partita_iva", "modello_brief", "lead_time_giorni", "email", "telefono", "note"]),
    "progetto": (Progetto, ["nome", "cliente", "produttore", "tipo_prodotto", "sviluppo", "versione_formula", "responsabile", "quantita_prevista", "prezzo_target", "data_consegna_richiesta", "lead_time_giorni", "campione_packaging", "stato", "brief"]),
    "formula": (Formula, ["codice", "nome", "produttore", "progetto", "categoria"]),
    "versioneformula": (VersioneFormula, ["formula", "inci", "modifiche", "data"]),
    "campionatura": (Campionatura, ["progetto", "versione_formula", "data_invio", "esito", "feedback", "data_feedback"]),
    "stabilita": (TestStabilita, ["progetto", "versione_formula", "data_inizio", "durata_giorni", "esito", "data_esito", "note"]),
    "quotazione": (Quotazione, ["progetto", "versione_formula", "data", "valida_fino", "commissione_pct", "margine_obiettivo_pct", "stato", "motivo", "note"]),
    "rigaquotazione": (RigaQuotazione, ["quotazione", "tipo", "descrizione", "quantita", "costo_unitario", "costi_fissi", "prezzo_unitario"]),
    "componente": (Componente, ["codice", "tipo", "descrizione", "materiale", "formato", "note"]),
    "artwork": (Artwork, ["cliente", "progetto", "nome", "versione_formula", "stato", "data_tds_richiesto", "data_tds_ricevuto", "file_tds", "file", "data_approvazione", "costo_impianto", "prezzo_impianto", "impianto_ordinato", "impianto_fatturato", "note"]),
    "packaging": (Packaging, ["cliente", "componente", "descrizione", "decorazione", "colore", "artwork", "riporta_inci", "moq", "costo_unitario", "prezzo_unitario", "note"]),
    "prodotto": (Prodotto, ["codice", "nome", "cliente", "progetto", "versione_formula", "formato", "prossima_consegna", "hs_code", "pezzi_per_cartone", "un_numero", "un_denominazione", "un_classe", "un_ems", "quantita_limitata", "imballo_interno", "attivo"]),
    "rigadistinta": (RigaDistinta, ["prodotto", "packaging", "quantita_per_pezzo", "etichetta_correttiva"]),
    "movimento": (MovimentoPackaging, ["packaging", "produttore", "data", "tipo", "quantita", "note"]),
    "ordine": (OrdineCliente, ["cliente", "progetto", "produttore", "data", "data_consegna_prevista", "stato", "riferimento_cliente", "note"]),
    "rigaordine": (RigaOrdine, ["ordine", "prodotto", "quantita", "prezzo_unitario", "lotto"]),
    "vocelistino": (VoceListino, ["produttore", "formula", "tipo", "descrizione", "quantita_minima", "costo_unitario", "prezzo_unitario", "valido_dal", "valido_fino", "note"]),
    "promemoria": (Promemoria, ["testo", "scadenza", "cliente", "progetto", "assegnato_a", "fatto"]),
    "azienda": (Azienda, ["ragione_sociale", "partita_iva", "codice_fiscale", "regime_fiscale", "indirizzo", "cap", "comune", "provincia", "codice_paese", "iban", "email", "telefono", "logo", "piede_documenti", "contatto_emergenza", "dichiarante"]),
    "acquisto": (OrdineAcquisto, ["produttore", "ordine", "data", "data_consegna_richiesta", "stato", "ddt_fornitore", "fattura_fornitore", "importo_fattura_fornitore", "note"]),
    "rigaacquisto": (RigaAcquisto, ["ordine_acquisto", "tipo", "descrizione", "quantita", "costo_unitario"]),
    "ddt": (DDT, ["cliente", "ordine", "data", "luogo_partenza", "destinazione", "causale", "vettore", "porto", "colli", "peso_kg", "peso_netto_kg", "aspetto", "note"]),
    "spedizione": (Spedizione, ["cliente", "ordine", "data", "riferimenti", "resa", "vettore", "nave_viaggio", "container", "sigillo", "porto_imbarco", "porto_sbarco", "destinazione", "note"]),
    "collo": (Collo, ["spedizione", "prodotto", "descrizione", "quantita", "lotto", "cartoni", "peso_lordo_kg", "peso_netto_kg", "dimensioni", "un", "descrizione_adr"]),
    "rigaddt": (RigaDDT, ["ddt", "codice", "descrizione", "quantita", "lotto"]),
    "prefattura": (PreFattura, ["cliente", "ordine", "ddt", "data", "aliquota_iva", "natura", "pagamento", "data_scadenza", "stato", "numero_fattura", "data_fattura", "pagata", "data_pagamento", "note"]),
    "rigaprefattura": (RigaPreFattura, ["prefattura", "tipo", "codice", "descrizione", "quantita", "prezzo_unitario"]),
}


def _next(request, default):
    url = request.POST.get("next") or request.GET.get("next")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return default


def _negato(request, default="/"):
    messages.error(request, "Il tuo ruolo non permette questa operazione. Chiedi a un amministratore se ti serve.")
    return redirect(_next(request, request.META.get("HTTP_REFERER") or default))


def richiede(azione, modello):
    """Decoratore: l'utente deve avere il permesso indicato sul modello."""
    from functools import wraps

    def decoratore(vista):
        @wraps(vista)
        @login_required
        def interna(request, *args, **kwargs):
            if not puo(request.user, azione, modello):
                return _negato(request)
            return vista(request, *args, **kwargs)

        return interna

    return decoratore


def _campo_form(campo, **kwargs):
    from django.db import models as m

    if isinstance(campo, m.DateField):
        kwargs["widget"] = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    elif isinstance(campo, m.TextField):
        kwargs["widget"] = forms.Textarea(attrs={"rows": 3})
    return campo.formfield(**kwargs)


def _restringi_scelte(form, contesto):
    """Limita le tendine ai record coerenti con cliente / progetto del contesto."""
    progetto = contesto.get("progetto")
    cliente = contesto.get("cliente") or (progetto.cliente if progetto else None)
    f = form.fields
    if progetto and "versione_formula" in f:
        f["versione_formula"].queryset = VersioneFormula.objects.filter(
            Q(formula__progetto=progetto) | Q(formula__progetto__isnull=True)
        ).select_related("formula")
    if cliente:
        for nome, modello in (("packaging", Packaging), ("artwork", Artwork), ("prodotto", Prodotto), ("progetto", Progetto)):
            if nome in f and not isinstance(f[nome].widget, forms.HiddenInput):
                f[nome].queryset = modello.objects.filter(cliente=cliente)


def _contesto(obj, iniziali):
    """Ricava progetto e cliente dal record in modifica o dai parametri dell'URL."""
    ctx = {}
    progetto = flusso.progetto_di(obj) if obj else None
    if not progetto and iniziali.get("progetto"):
        progetto = Progetto.objects.filter(pk=iniziali["progetto"]).first()
    if not progetto and iniziali.get("formula"):
        formula = Formula.objects.filter(pk=iniziali["formula"]).first()
        progetto = formula.progetto if formula else None
    if progetto:
        ctx["progetto"] = progetto
    cliente = getattr(obj, "cliente", None) if obj else None
    if not cliente:
        for chiave, modello in (("cliente", Cliente), ("prodotto", Prodotto), ("ordine", OrdineCliente)):
            if iniziali.get(chiave):
                rec = modello.objects.filter(pk=iniziali[chiave]).first()
                cliente = rec if chiave == "cliente" else getattr(rec, "cliente", None)
                break
    if not cliente and obj is not None:
        for attr in ("prodotto", "ordine"):
            genitore = getattr(obj, attr, None)
            if genitore is not None:
                cliente = genitore.cliente
    if cliente:
        ctx["cliente"] = cliente
    return ctx


@login_required
def modifica(request, modello, pk=None):
    if modello not in CRUD:
        raise Http404
    Model, campi = CRUD[modello]
    obj = get_object_or_404(Model, pk=pk) if pk else None
    if not puo(request.user, "change" if obj else "add", Model):
        return _negato(request, obj.get_absolute_url() if obj else "/")
    iniziali = {k: v for k, v in request.GET.items() if k in campi}
    Form = modelform_factory(Model, fields=campi, formfield_callback=_campo_form)
    form = Form(request.POST or None, request.FILES or None, instance=obj, initial=iniziali)
    if obj is None:
        for nome in iniziali:
            if isinstance(form.fields[nome], forms.ModelChoiceField):
                form.fields[nome].widget = forms.HiddenInput()
    _restringi_scelte(form, _contesto(obj, iniziali))
    if request.method == "POST" and form.is_valid():
        salvato = form.save()
        flusso.dopo_salvataggio(salvato, request.user, creato=obj is None)
        messages.success(request, f"{Model._meta.verbose_name.capitalize()} salvato.")
        return redirect(_next(request, salvato.get_absolute_url()))
    return render(
        request,
        "ws/form.html",
        {
            "form": form,
            "obj": obj,
            "modello": modello,
            "titolo": ("Modifica " if obj else "Nuovo: ") + str(Model._meta.verbose_name),
            "next": _next(request, obj.get_absolute_url() if obj else "/"),
        },
    )


@login_required
@require_POST
def elimina(request, modello, pk):
    if modello not in CRUD:
        raise Http404
    obj = get_object_or_404(CRUD[modello][0], pk=pk)
    if not puo(request.user, "delete", CRUD[modello][0]):
        return _negato(request)
    try:
        obj.delete()
        messages.success(request, "Eliminato.")
    except ProtectedError:
        messages.error(request, "Impossibile eliminare: il record è usato da altri dati.")
    return redirect(_next(request, "/"))


# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    aperti = Progetto.objects.filter(stato=Progetto.Stato.APERTO).select_related("cliente", "produttore")
    per_fase = dict(aperti.values_list("fase").annotate(n=Count("pk")))
    fasi = [{"valore": v, "nome": n, "n": per_fase.get(v, 0)} for v, n in Progetto.Fase.choices]
    stabilita = [
        t
        for t in TestStabilita.objects.filter(
            esito=TestStabilita.Esito.IN_CORSO, progetto__stato=Progetto.Stato.APERTO
        ).select_related("progetto", "versione_formula__formula")
    ]
    stabilita.sort(key=lambda t: t.data_fine_prevista)
    return render(
        request,
        "ws/dashboard.html",
        {
            "fasi": fasi,
            "n_aperti": aperti.count(),
            "avvisi_inci": flusso.tutti_avvisi_inci(),
            "stabilita": stabilita,
            "in_ritardo": [p for p in aperti if flusso.in_ritardo(p)],
            "quotazioni": Quotazione.objects.filter(
                stato=Quotazione.Stato.INVIATA, progetto__stato=Progetto.Stato.APERTO
            ).select_related("progetto__cliente"),
            "campionature": Campionatura.objects.filter(
                esito=Campionatura.Esito.ATTESA, progetto__stato=Progetto.Stato.APERTO
            ).select_related("progetto__cliente", "versione_formula__formula"),
            "eventi": Evento.objects.select_related("progetto", "utente")[:12],
            "promemoria": Promemoria.objects.filter(fatto=False).select_related("cliente", "progetto", "assegnato_a")[:30],
            "pagamenti": flusso.pagamenti_da_verificare(),
            "riordini": flusso.riordini_da_sollecitare(),
            "tds": flusso.tds_da_sollecitare(),
            "fatture_diverse": flusso.fatture_produttore_diverse(),
            "posta_da_gestire": MessaggioPosta.objects.exclude(stato=MessaggioPosta.Stato.GESTITO).count(),
            "oggi": flusso.oggi(),
        },
    )


@login_required
def progetti(request):
    stato = request.GET.get("stato", Progetto.Stato.APERTO)
    qs = Progetto.objects.select_related("cliente", "produttore")
    if stato != "tutti":
        qs = qs.filter(stato=stato)
    lista = list(qs)
    for p in lista:
        p.ritardo = flusso.in_ritardo(p)
    colonne = [{"nome": n, "progetti": [p for p in lista if p.fase == v]} for v, n in Progetto.Fase.choices]
    return render(
        request,
        "ws/progetti.html",
        {"colonne": colonne, "stato": stato, "stati": Progetto.Stato.choices, "totale": len(lista)},
    )


@login_required
def progetto(request, pk):
    p = get_object_or_404(Progetto.objects.select_related("cliente", "produttore", "responsabile"), pk=pk)
    controlli = flusso.controlli(p)
    i = flusso.indice_fase(p.fase)
    fasi = [
        {"valore": v, "nome": n, "stato": "fatta" if k < i else "corrente" if k == i else "futura"}
        for k, (v, n) in enumerate(Progetto.Fase.choices)
        if not flusso.fase_saltata(p, v)
    ]
    succ = flusso.fase_successiva(p)
    return render(
        request,
        "ws/progetto.html",
        {
            "p": p,
            "pk_testo": str(p.pk),
            "fasi": fasi,
            "fasi_precedenti": [f for f in fasi if f["stato"] == "fatta"],
            "richiede_stabilita": flusso.richiede_stabilita(p),
            "controlli": controlli,
            "puo_avanzare": succ is not None and all(c.ok for c in controlli),
            "fase_successiva": Progetto.Fase(succ).label if succ else None,
            "planner": flusso.planner(p),
            "avvisi": flusso.avvisi_progetto(p),
            "formula_approvata": flusso.formula_approvata(p),
            "quotazioni": p.quotazioni.prefetch_related("righe").select_related("versione_formula__formula"),
            "campionature": p.campionature.select_related("versione_formula__formula"),
            "stabilita": p.stabilita.select_related("versione_formula__formula"),
            "formule": p.formule.prefetch_related("versioni"),
            "artwork": p.artwork.select_related("versione_formula__formula"),
            "prodotti": p.prodotti.select_related("versione_formula__formula"),
            "ordini": p.ordini.prefetch_related("righe"),
            "eventi": p.eventi.select_related("utente")[:40],
            "promemoria": p.promemoria.filter(fatto=False).select_related("assegnato_a"),
            "brief": p.brief_produttore.all(),
        },
    )


@richiede("change", Progetto)
@require_POST
def progetto_avanza(request, pk):
    p = get_object_or_404(Progetto, pk=pk)
    try:
        flusso.avanza(p, request.user)
        messages.success(request, f"Progetto passato alla fase «{p.get_fase_display()}».")
    except flusso.FlussoError as e:
        messages.error(request, str(e))
    return redirect(p)


@richiede("change", Progetto)
@require_POST
def progetto_arretra(request, pk):
    p = get_object_or_404(Progetto, pk=pk)
    try:
        flusso.riporta_a_fase(p, request.POST.get("fase", ""), request.POST.get("motivo", ""), request.user)
        messages.success(request, f"Progetto riportato alla fase «{p.get_fase_display()}».")
    except (flusso.FlussoError, ValueError) as e:
        messages.error(request, str(e))
    return redirect(p)


@richiede("add", Evento)
@require_POST
def progetto_nota(request, pk):
    p = get_object_or_404(Progetto, pk=pk)
    testo = request.POST.get("testo", "").strip()
    if testo:
        Evento.objects.create(progetto=p, utente=request.user, testo=testo)
    return redirect(p)


# --------------------------------------------------------------------------
@login_required
def clienti(request):
    q = request.GET.get("q", "").strip()
    qs = Cliente.objects.annotate(
        n_progetti=Count("progetti", filter=Q(progetti__stato=Progetto.Stato.APERTO), distinct=True),
        n_prodotti=Count("prodotti", distinct=True),
    )
    if q:
        qs = qs.filter(ragione_sociale__icontains=q)
    return render(request, "ws/clienti.html", {"clienti": qs, "q": q})


@login_required
def cliente(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    return render(
        request,
        "ws/cliente.html",
        {
            "c": c,
            "pk_testo": str(c.pk),
            "progetti": c.progetti.select_related("produttore"),
            "prodotti": c.prodotti.select_related("versione_formula__formula"),
            "ordini": c.ordini.prefetch_related("righe")[:20],
            "giacenze": flusso.giacenze(c),
            "promemoria": c.promemoria.filter(fatto=False).select_related("progetto", "assegnato_a"),
        },
    )


@login_required
def produttori(request):
    qs = Produttore.objects.annotate(
        n_progetti=Count("progetti", filter=Q(progetti__stato=Progetto.Stato.APERTO), distinct=True)
    )
    return render(request, "ws/produttori.html", {"produttori": qs})


@login_required
def formule(request):
    qs = Formula.objects.select_related("produttore", "progetto").prefetch_related("versioni")
    return render(request, "ws/formule.html", {"formule": qs})


@login_required
def prodotti(request):
    lista = list(Prodotto.objects.select_related("cliente", "versione_formula__formula").annotate(n_righe=Count("distinta")))
    aperti = {}
    for a in flusso.tutti_avvisi_inci():
        aperti[a["prodotto"].pk] = aperti.get(a["prodotto"].pk, 0) + 1
    for p in lista:
        p.avvisi = aperti.get(p.pk, 0)
    return render(request, "ws/prodotti.html", {"prodotti": lista})


@login_required
def prodotto(request, pk):
    p = get_object_or_404(Prodotto.objects.select_related("cliente", "progetto", "versione_formula__formula"), pk=pk)
    avvisi = {a["riga"].pk: a for a in flusso.avvisi_inci(p)}
    righe = list(p.distinta.select_related("packaging__componente", "packaging__artwork__versione_formula__formula"))
    for r in righe:
        r.avviso = avvisi.get(r.pk)
        r.giacenza = r.packaging.giacenza()
    return render(
        request,
        "ws/prodotto.html",
        {
            "p": p,
            "righe": righe,
            "avvisi": [a for a in avvisi.values()],
            "ordini": RigaOrdine.objects.filter(prodotto=p).select_related("ordine")[:20],
        },
    )


@login_required
def catalogo(request):
    return render(
        request,
        "ws/catalogo.html",
        {
            "componenti": Componente.objects.all(),
            "packaging": Packaging.objects.select_related("cliente", "componente", "artwork__versione_formula__formula"),
        },
    )


@login_required
def magazzino(request):
    righe = flusso.giacenze()
    return render(
        request,
        "ws/magazzino.html",
        {
            "giacenze": righe,
            "totale": sum(g["quantita"] for g in righe),
            "movimenti": MovimentoPackaging.objects.select_related("packaging__cliente", "produttore", "ordine")[:40],
        },
    )


@login_required
def listino(request):
    q = request.GET.get("q", "").strip()
    scadute = request.GET.get("scadute") == "1"
    quotazione = Quotazione.objects.filter(pk=request.GET.get("quotazione") or 0).select_related("progetto").first()
    return render(
        request,
        "ws/listino.html",
        {
            "voci": flusso.voci_listino(q, scadute),
            "righe": flusso.listino(q)[:300],
            "q": q,
            "scadute": scadute,
            "quotazione": quotazione,
        },
    )


@login_required
def ordini(request):
    qs = OrdineCliente.objects.select_related("cliente", "produttore").prefetch_related("righe")
    return render(request, "ws/ordini.html", {"ordini": qs})


def _ordine(pk):
    return get_object_or_404(OrdineCliente.objects.select_related("cliente", "produttore", "progetto"), pk=pk)


@login_required
def ordine(request, pk):
    o = _ordine(pk)
    righe = list(o.righe.select_related("prodotto__versione_formula__formula"))
    avvisi = []
    da_produrre = o.stato in (OrdineCliente.Stato.BOZZA, OrdineCliente.Stato.INVIATA, OrdineCliente.Stato.ACCETTATA)
    for r in righe if da_produrre else []:
        for a in flusso.avvisi_inci(r.prodotto):
            if not a["risolto"]:
                a["prodotto"] = r.prodotto
                avvisi.append(a)
    return render(
        request,
        "ws/ordine.html",
        {
            "o": o,
            "righe": righe,
            "fabbisogno": flusso.piano_packaging(o),
            "registrato": o.movimenti.exists(),
            "avvisi": avvisi,
            "acquisti": o.ordini_acquisto.prefetch_related("righe"),
            "ddt": o.ddt.all(),
            "prefatture": o.prefatture.prefetch_related("righe"),
        },
    )


@login_required
def ordine_stampa(request, pk):
    o = _ordine(pk)
    return render(request, "ws/ordine_stampa.html", {"o": o, "righe": o.righe.select_related("prodotto")})


@richiede("add", MovimentoPackaging)
@require_POST
def ordine_registra_packaging(request, pk):
    o = _ordine(pk)
    try:
        flusso.registra_packaging(o)
        messages.success(request, "Movimenti di packaging registrati: il residuo è ora a magazzino.")
    except flusso.FlussoError as e:
        messages.error(request, str(e))
    return redirect(o)


# --------------------------------------------------------------------------
# Documenti
# --------------------------------------------------------------------------
def _genera(request, pk, funzione):
    o = _ordine(pk)
    try:
        doc = funzione(o)
    except flusso.FlussoError as e:
        messages.error(request, str(e))
        return redirect(o)
    messages.success(request, f"Creato {doc._meta.verbose_name} {doc}. Controlla i dati prima di inviarlo.")
    return redirect(doc)


@richiede("add", OrdineAcquisto)
@require_POST
def ordine_genera_acquisto(request, pk):
    return _genera(request, pk, documenti.genera_ordine_acquisto)


@richiede("add", DDT)
@require_POST
def ordine_genera_ddt(request, pk):
    return _genera(request, pk, documenti.genera_ddt)


@richiede("add", PreFattura)
@require_POST
def ordine_genera_prefattura(request, pk):
    return _genera(request, pk, documenti.genera_prefattura)


@login_required
def acquisti(request):
    qs = OrdineAcquisto.objects.select_related("produttore", "ordine__cliente").prefetch_related("righe")
    return render(request, "ws/acquisti.html", {"acquisti": qs})


@login_required
def acquisto(request, pk):
    oa = get_object_or_404(OrdineAcquisto.objects.select_related("produttore", "ordine__cliente"), pk=pk)
    return render(request, "ws/acquisto.html", {"d": oa, "righe": oa.righe.all(), "azienda": Azienda.corrente()})


@login_required
def ddt_elenco(request):
    return render(request, "ws/ddt_elenco.html", {"ddt": DDT.objects.select_related("cliente", "ordine")})


@login_required
def ddt(request, pk):
    d = get_object_or_404(DDT.objects.select_related("cliente", "ordine"), pk=pk)
    return render(request, "ws/ddt.html", {"d": d, "righe": d.righe.all(), "azienda": Azienda.corrente()})


@login_required
def prefatture(request):
    qs = PreFattura.objects.select_related("cliente", "ordine").prefetch_related("righe")
    return render(request, "ws/prefatture.html", {"prefatture": qs})


@login_required
def prefattura(request, pk):
    pf = get_object_or_404(PreFattura.objects.select_related("cliente", "ordine", "ddt"), pk=pk)
    return render(
        request,
        "ws/prefattura.html",
        {"d": pf, "righe": pf.righe.all(), "azienda": Azienda.corrente(), "controlli": documenti.controlli_prefattura(pf)},
    )


@richiede("change", PreFattura)
def prefattura_esporta(request, pk, formato):
    from django.http import HttpResponse

    pf = get_object_or_404(PreFattura.objects.select_related("cliente", "ordine", "ddt"), pk=pk)
    if formato == "xml":
        contenuto, tipo, nome = documenti.prefattura_xml(pf), "application/xml", documenti.nome_file_xml(pf)
    elif formato == "csv":
        contenuto, tipo, nome = documenti.prefattura_csv(pf), "text/csv; charset=utf-8", f"{pf.numero}.csv"
    else:
        raise Http404
    if pf.stato == PreFattura.Stato.BOZZA:
        pf.stato = PreFattura.Stato.ESPORTATA
        pf.save(update_fields=["stato"])
    risposta = HttpResponse(contenuto, content_type=tipo)
    risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return risposta


@login_required
def azienda(request):
    a = Azienda.objects.first()
    if a is None:
        return redirect("nuovo", "azienda")
    return redirect("modifica", "azienda", a.pk)


@login_required
def allegato(request, percorso):
    """File caricati (artwork): visibili solo dopo l'accesso."""
    from django.conf import settings
    from django.views.static import serve

    return serve(request, percorso, document_root=settings.MEDIA_ROOT)


# --------------------------------------------------------------------------
# Quotazioni, listino, riordini, promemoria, ricerca
# --------------------------------------------------------------------------
@login_required
def quotazione_stampa(request, pk):
    q = get_object_or_404(Quotazione.objects.select_related("progetto__cliente", "progetto__produttore", "versione_formula__formula"), pk=pk)
    return render(request, "ws/quotazione_stampa.html", {"q": q, "righe": q.righe.all(), "azienda": Azienda.corrente()})


@richiede("add", Quotazione)
@require_POST
def quotazione_duplica(request, pk):
    q = get_object_or_404(Quotazione, pk=pk)
    nuova = flusso.duplica_quotazione(q)
    flusso.dopo_salvataggio(nuova, request.user, creato=True)
    messages.success(request, f"Creata la versione {nuova.numero} in bozza: modifica le voci e indica il motivo della revisione.")
    return redirect("modifica", "quotazione", nuova.pk)


@richiede("add", VoceListino)
@require_POST
def listino_salva_riga(request, pk):
    riga = get_object_or_404(RigaQuotazione.objects.select_related("quotazione__progetto"), pk=pk)
    try:
        flusso.riga_in_listino(riga)
        messages.success(request, "Voce salvata nel listino.")
    except flusso.FlussoError as e:
        messages.error(request, str(e))
    return redirect(_next(request, reverse("listino")))


@richiede("add", RigaQuotazione)
@require_POST
def listino_usa(request, pk, quotazione):
    voce = get_object_or_404(VoceListino, pk=pk)
    q = get_object_or_404(Quotazione, pk=quotazione)
    flusso.voce_in_quotazione(voce, q)
    messages.success(request, f"Voce aggiunta alla quotazione n. {q.numero}: controlla la quantità.")
    return redirect(q.progetto)


@richiede("add", OrdineCliente)
@require_POST
def prodotto_riordino(request, pk):
    p = get_object_or_404(Prodotto, pk=pk)
    try:
        ordine = flusso.crea_riordino(p)
    except flusso.FlussoError as e:
        messages.error(request, str(e))
        return redirect(p)
    messages.success(request, "Riordino creato in bozza con quantità e prezzo dell'ultimo ordine: controllali.")
    return redirect(ordine)


@richiede("change", Promemoria)
@require_POST
def promemoria_fatto(request, pk):
    p = get_object_or_404(Promemoria, pk=pk)
    p.fatto = True
    p.save(update_fields=["fatto"])
    if p.progetto_id:
        Evento.objects.create(progetto=p.progetto, utente=request.user, testo=f"Fatto: {p.testo}", automatico=True)
    return redirect(_next(request, request.META.get("HTTP_REFERER") or "/"))


@login_required
def cerca(request):
    q = request.GET.get("q", "").strip()
    gruppi = []
    if len(q) >= 2:
        ricerche = [
            ("Clienti", Cliente.objects.filter(Q(ragione_sociale__icontains=q) | Q(partita_iva__icontains=q))),
            ("Progetti", Progetto.objects.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(tipo_prodotto__icontains=q))),
            ("Prodotti", Prodotto.objects.filter(Q(nome__icontains=q) | Q(codice__icontains=q))),
            ("Formule", Formula.objects.filter(Q(nome__icontains=q) | Q(codice__icontains=q))),
            ("Packaging", Packaging.objects.filter(Q(descrizione__icontains=q) | Q(codice__icontains=q) | Q(colore__icontains=q))),
            ("Ordini clienti", OrdineCliente.objects.filter(Q(numero__icontains=q) | Q(riferimento_cliente__icontains=q))),
            ("Ordini ai produttori", OrdineAcquisto.objects.filter(Q(numero__icontains=q) | Q(fattura_fornitore__icontains=q))),
            ("Pre-fatture", PreFattura.objects.filter(Q(numero__icontains=q) | Q(numero_fattura__icontains=q))),
        ]
        sezione = {"Clienti": "clienti", "Progetti": "progetti", "Prodotti": "prodotti", "Formule": "formule", "Packaging": "prodotti", "Ordini clienti": "ordini", "Ordini ai produttori": "acquisti", "Pre-fatture": "fatture"}
        nascoste = sezioni_nascoste(request.user)
        gruppi = [(nome, list(qs[:15])) for nome, qs in ricerche if sezione[nome] not in nascoste]
        gruppi = [g for g in gruppi if g[1]]
    return render(request, "ws/cerca.html", {"q": q, "gruppi": gruppi})


# --------------------------------------------------------------------------
# PDF su carta intestata
# --------------------------------------------------------------------------
DOCUMENTI_PDF = {
    "offerta": (Quotazione, "ws/quotazione_stampa.html", "q", lambda o: f"Offerta {o.progetto.codice}-{o.numero}"),
    "conferma": (OrdineCliente, "ws/ordine_stampa.html", "o", lambda o: f"Conferma d'ordine {o.numero}"),
    "ddt": (DDT, "ws/ddt.html", "d", lambda o: f"DDT {o.numero}"),
    "prefattura": (PreFattura, "ws/prefattura.html", "d", lambda o: f"Pre-fattura {o.numero}"),
    "acquisto": (OrdineAcquisto, "ws/acquisto.html", "d", lambda o: f"Ordine d'acquisto {o.numero}"),
    "packing": (Spedizione, "ws/packing_list.html", "sp", lambda o: f"Packing list {o.numero}"),
    "multimodale": (Spedizione, "ws/multimodale.html", "sp", lambda o: f"Multimodal DGD {o.numero}"),
}


def crea_pdf(request, tipo, obj):
    """Restituisce (nome file, bytes) del documento impaginato sulla carta intestata."""
    from django.contrib.staticfiles import finders
    from django.template.loader import render_to_string
    from weasyprint import HTML

    _, template, variabile, nome = DOCUMENTI_PDF[tipo]
    az = Azienda.corrente()
    font = finders.find("ws/font/inter-latin-wght-normal.woff2")
    from django.utils import translation

    from .templatetags.formati import lingua_di

    lingua = lingua_di({variabile: obj})
    with translation.override(lingua):  # numeri e date nel formato della lingua del documento
        html = _html_pdf(request, template, variabile, obj, az, font)
    return f"{nome(obj)}.pdf", HTML(string=html).write_pdf()


def _html_pdf(request, template, variabile, obj, az, font):
    from django.template.loader import render_to_string

    return render_to_string(
        template,
        {
            variabile: obj,
            "righe": obj.righe.all() if hasattr(obj, "righe") else [],
            "azienda": az,
            "base_template": "ws/pdf_base.html",
            "logo_url": f"file://{az.logo.path}" if az.pk and az.logo else "",
            "font_url": f"file://{font}" if font else "",
            "pericolose": obj.merci_pericolose() if isinstance(obj, Spedizione) else [],
        },
        request=request,
    )


@login_required
def pdf(request, tipo, pk):
    from django.http import HttpResponse

    if tipo not in DOCUMENTI_PDF:
        raise Http404
    obj = get_object_or_404(DOCUMENTI_PDF[tipo][0], pk=pk)
    nome, contenuto = crea_pdf(request, tipo, obj)
    risposta = HttpResponse(contenuto, content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="{nome}"'
    return risposta


# --------------------------------------------------------------------------
# Brief al produttore
# --------------------------------------------------------------------------
def _precompila_brief(campi, progetto):
    """Valori iniziali presi dal progetto, riconoscendo i campi dall'etichetta."""
    az = Azienda.corrente()
    regole = [
        ("CUSTOMER", az.ragione_sociale),
        ("PROJECT NAME", progetto.nome),
        ("DESCRIPTION", progetto.brief),
        ("LAUNCH DATE", progetto.data_consegna_richiesta.strftime("%d/%m/%Y") if progetto.data_consegna_richiesta else ""),
        ("TARGET PRICE", f"{progetto.prezzo_target:.2f} EUR".replace(".", ",") if progetto.prezzo_target else ""),
        ("MARKET", progetto.cliente.paese),
        ("MOQ", str(progetto.quantita_prevista or "")),
        ("DATE", flusso.oggi().strftime("%d/%m/%Y")),
    ]
    valori = {}
    for c in campi:
        if c.tipo == "casella":
            continue
        etichetta = c.etichetta.upper()
        for chiave, valore in regole:
            if valore and (etichetta == chiave or (chiave != "DATE" and etichetta.startswith(chiave))):
                valori[c.chiave] = valore
                break
    return valori


@richiede("add", Brief)
@require_POST
def brief_nuovo(request, pk):
    from django.core.files.base import ContentFile

    from . import brief as modulo

    p = get_object_or_404(Progetto.objects.select_related("produttore", "cliente"), pk=pk)
    if not p.produttore_id or not p.produttore.modello_brief:
        messages.error(request, "Carica prima il modello del brief (file Word vuoto) nella scheda del produttore.")
        return redirect(p)
    with p.produttore.modello_brief.open("rb") as f:
        dati = f.read()
    try:
        campi = modulo.analizza(dati)
    except modulo.BriefError as e:
        messages.error(request, str(e))
        return redirect(p)
    b = Brief(progetto=p, valori=_precompila_brief(campi, p))
    b.modello.save(f"modello-{p.codice}.docx", ContentFile(dati), save=False)
    b.save()
    flusso.dopo_salvataggio(b, request.user, creato=True)
    return redirect(b)


def _campi_brief(b):
    from . import brief as modulo

    with b.modello.open("rb") as f:
        dati = f.read()
    return dati, modulo.analizza(dati)


@login_required
def brief(request, pk):
    from . import brief as modulo

    b = get_object_or_404(Brief.objects.select_related("progetto__cliente", "progetto__produttore"), pk=pk)
    _, campi = _campi_brief(b)
    if request.method == "POST":
        if not puo(request.user, "change", Brief):
            return _negato(request, b.get_absolute_url())
        valori = {}
        for c in campi:
            if c.tipo == "casella":
                if request.POST.get(c.chiave):
                    valori[c.chiave] = True
            else:
                testo = request.POST.get(c.chiave, "").strip()
                if testo and (c.tipo != "menu" or testo in c.opzioni):
                    valori[c.chiave] = testo
        b.valori = valori
        b.stato = request.POST.get("stato") if request.POST.get("stato") in Brief.Stato.values else b.stato
        b.note = request.POST.get("note", "")
        if b.stato != Brief.Stato.BOZZA and not b.data_invio:
            b.data_invio = flusso.oggi()
        b.save()
        flusso.dopo_salvataggio(b, request.user)
        messages.success(request, "Brief salvato.")
        if request.POST.get("azione") == "scarica":
            return redirect("brief_scarica", b.pk)
        return redirect(b)
    for c in campi:
        c.valore = b.valori.get(c.chiave, False if c.tipo == "casella" else "")
    compilati = sum(1 for c in campi if c.valore)
    return render(
        request,
        "ws/brief.html",
        {"b": b, "sezioni": modulo.sezioni(campi), "compilati": compilati, "totale": len(campi), "stati": Brief.Stato.choices},
    )


@login_required
def brief_scarica(request, pk):
    from django.http import HttpResponse

    from . import brief as modulo

    b = get_object_or_404(Brief.objects.select_related("progetto"), pk=pk)
    dati, _ = _campi_brief(b)
    risposta = HttpResponse(
        modulo.compila(dati, b.valori),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    nome = "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in b.progetto.nome).strip()
    risposta["Content-Disposition"] = f'attachment; filename="Technical Brief {nome}.docx"'
    return risposta


# --------------------------------------------------------------------------
# Spedizioni
# --------------------------------------------------------------------------
@richiede("add", Spedizione)
@require_POST
def ordine_genera_spedizione(request, pk):
    return _genera(request, pk, documenti.genera_spedizione)


@login_required
def spedizioni(request):
    qs = Spedizione.objects.select_related("cliente", "ordine").prefetch_related("colli")
    return render(request, "ws/spedizioni.html", {"spedizioni": qs})


@login_required
def spedizione(request, pk):
    sp = get_object_or_404(Spedizione.objects.select_related("cliente", "ordine"), pk=pk)
    az = Azienda.corrente()
    mancanti = []
    pericolose = sp.merci_pericolose()
    if pericolose:
        if not az.contatto_emergenza:
            mancanti.append("contatto d'emergenza 24h (in Dati azienda)")
        if not az.dichiarante:
            mancanti.append("dichiarante (in Dati azienda)")
        for g in pericolose:
            p = g["prodotto"]
            if p is None and not g["collo"].descrizione_adr:
                mancanti.append(f"descrizione per la dichiarazione sul pallet {g['collo'].numero}")
            elif p is not None and not (p.un_denominazione and p.un_classe):
                mancanti.append(f"denominazione di trasporto e classe sul prodotto {p.codice}")
    return render(
        request,
        "ws/spedizione.html",
        {"sp": sp, "colli": sp.colli.select_related("prodotto"), "pericolose": pericolose, "mancanti": mancanti},
    )


# --------------------------------------------------------------------------
# Utenti e accessi (solo il gestore)
# --------------------------------------------------------------------------
def _solo_gestore(vista):
    from functools import wraps

    @wraps(vista)
    @login_required
    def interna(request, *args, **kwargs):
        if not request.user.is_superuser:
            return _negato(request)
        return vista(request, *args, **kwargs)

    return interna


@_solo_gestore
def utenti(request):
    from django.contrib.auth import get_user_model

    lista = list(get_user_model().objects.order_by("username").prefetch_related("groups"))
    for u in lista:
        u.prof = profilo_di(u)
        u.nascoste = [SEZIONI[s][0] for s in (u.prof.sezioni_nascoste if u.prof else []) if s in SEZIONI]
    return render(request, "ws/utenti.html", {"utenti": lista})


@_solo_gestore
def utente(request, pk=None):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    User = get_user_model()
    u = get_object_or_404(User, pk=pk) if pk else None
    prof = profilo_di(u) if u else None
    errori = []
    dati = request.POST if request.method == "POST" else None
    if dati is not None:
        username = dati.get("username", "").strip()
        password = dati.get("password", "")
        produttore = Produttore.objects.filter(pk=dati.get("produttore") or 0).first()
        gestore = bool(dati.get("gestore")) and produttore is None
        if not username:
            errori.append("Indica il nome utente.")
        elif User.objects.filter(username__iexact=username).exclude(pk=pk or 0).exists():
            errori.append("Esiste già un utente con questo nome.")
        if u is None and not password:
            errori.append("Indica una password iniziale.")
        if password:
            try:
                validate_password(password)
            except ValidationError as e:
                errori += list(e.messages)
        if u is not None and u == request.user and (not gestore or not dati.get("attivo")):
            errori.append("Non puoi togliere a te stesso il ruolo di gestore o disattivarti.")
        if not errori:
            u = u or User()
            u.username, u.first_name, u.last_name, u.email = username, dati.get("nome", "").strip(), dati.get("cognome", "").strip(), dati.get("email", "").strip()
            u.is_active, u.is_superuser, u.is_staff = bool(dati.get("attivo")), gestore, gestore
            if password:
                u.set_password(password)
            u.save()
            # un utente del produttore non ha ruoli interni
            u.groups.set([] if produttore else Group.objects.filter(name__in=dati.getlist("ruoli")))
            Profilo.objects.update_or_create(
                user=u,
                defaults={"produttore": produttore, "sezioni_nascoste": [] if produttore else [s for s in dati.getlist("nascoste") if s in SEZIONI]},
            )
            messages.success(request, f"Utente {u.username} salvato.")
            return redirect("utenti")
    return render(
        request,
        "ws/utente.html",
        {
            "u": u,
            "prof": prof,
            "errori": errori,
            "dati": dati,
            "ruoli": [(r, u is not None and u.groups.filter(name=r).exists()) for r in RUOLI],
            "sezioni": [(k, nome, prof is not None and k in (prof.sezioni_nascoste or [])) for k, (nome, _) in SEZIONI.items()],
            "produttori": Produttore.objects.all(),
        },
    )


# --------------------------------------------------------------------------
# Area riservata al produttore: solo i suoi progetti, senza prezzi né clienti
# --------------------------------------------------------------------------
def _produttore_di(request):
    prof = profilo_di(request.user)
    if prof is None or not prof.produttore_id:
        raise Http404
    return prof.produttore


@login_required
def portale(request):
    prod = _produttore_di(request)
    progetti = list(prod.progetti.filter(stato=Progetto.Stato.APERTO).order_by("-creato"))
    for p in progetti:
        p.formula = flusso.formula_approvata(p)
        p.tds_attesi = p.artwork.filter(stato=Artwork.Stato.ATTESA_TDS).count()
    ordini = prod.ordini_acquisto.exclude(stato__in=[OrdineAcquisto.Stato.BOZZA, OrdineAcquisto.Stato.ANNULLATO]).prefetch_related("righe")[:20]
    return render(request, "ws/portale.html", {"prod": prod, "progetti": progetti, "ordini": ordini})


@login_required
def portale_progetto(request, pk):
    prod = _produttore_di(request)
    p = get_object_or_404(Progetto, pk=pk, produttore=prod)
    return render(
        request,
        "ws/portale_progetto.html",
        {
            "prod": prod,
            "p": p,
            "formula_approvata": flusso.formula_approvata(p),
            "formule": p.formule.prefetch_related("versioni"),
            "campionature": p.campionature.select_related("versione_formula__formula"),
            "stabilita": p.stabilita.select_related("versione_formula__formula"),
            "artwork": p.artwork.select_related("versione_formula__formula"),
            "brief": p.brief_produttore.exclude(stato=Brief.Stato.BOZZA),
            "ordini": prod.ordini_acquisto.filter(ordine__progetto=p).exclude(stato=OrdineAcquisto.Stato.BOZZA).prefetch_related("righe"),
        },
    )


@login_required
def portale_file(request, tipo, pk):
    """File di un progetto del produttore: artwork, TDS o brief compilato."""
    from django.http import FileResponse, HttpResponse

    prod = _produttore_di(request)
    if tipo == "brief":
        from . import brief as modulo

        b = get_object_or_404(Brief.objects.exclude(stato=Brief.Stato.BOZZA), pk=pk, progetto__produttore=prod)
        dati, _ = _campi_brief(b)
        risposta = HttpResponse(modulo.compila(dati, b.valori), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        risposta["Content-Disposition"] = f'attachment; filename="Technical Brief {b.progetto.codice}-{b.numero}.docx"'
        return risposta
    a = get_object_or_404(Artwork, pk=pk, progetto__produttore=prod)
    f = {"artwork": a.file, "tds": a.file_tds}.get(tipo)
    if not f:
        raise Http404
    return FileResponse(f.open("rb"), as_attachment=True, filename=f.name.rsplit("/", 1)[-1])


@login_required
@require_POST
def portale_tds(request, pk):
    """Il produttore carica il TDS: l'artwork passa al cliente e il progetto lo registra nel diario."""
    prod = _produttore_di(request)
    a = get_object_or_404(Artwork, pk=pk, progetto__produttore=prod)
    f = request.FILES.get("file")
    if not f:
        messages.error(request, "Scegli il file del TDS da caricare.")
    else:
        a.file_tds.save(f.name, f, save=False)
        a.data_tds_ricevuto = flusso.oggi()
        if a.stato == Artwork.Stato.ATTESA_TDS:
            a.stato = Artwork.Stato.BOZZA
        a.save()
        Evento.objects.create(progetto=a.progetto, utente=request.user, testo=f"TDS per «{a.nome}» caricato dal produttore.", automatico=True)
        messages.success(request, "TDS caricato.")
    return redirect("portale_progetto", a.progetto_id)


# --------------------------------------------------------------------------
# Posta e assistente
# --------------------------------------------------------------------------
def crea_messaggio(dati_eml):
    """Salva una mail (.eml) con i suoi allegati."""
    from django.core.files.base import ContentFile

    from . import assistente
    from .models import AllegatoPosta

    letto = assistente.leggi_eml(dati_eml)
    m = MessaggioPosta(mittente=letto["mittente"][:300], destinatari=letto["destinatari"][:500], oggetto=letto["oggetto"][:500], data=letto["data"], corpo=letto["corpo"])
    m.originale.save("messaggio.eml", ContentFile(dati_eml), save=False)
    m.save()
    for nome, _, contenuto in letto["allegati"]:
        a = AllegatoPosta(messaggio=m, nome=nome[:255])
        a.file.save(nome, ContentFile(contenuto), save=True)
    return m


@login_required
def posta(request):
    from . import assistente

    stato = request.GET.get("stato", "aperti")
    qs = MessaggioPosta.objects.select_related("cliente", "produttore", "ordine", "ordine_acquisto").prefetch_related("allegati")
    if stato == "aperti":
        qs = qs.exclude(stato=MessaggioPosta.Stato.GESTITO)
    return render(request, "ws/posta.html", {"messaggi": qs[:200], "stato": stato, "configurato": assistente.configurato(), "tipi": assistente.TIPI})


@richiede("add", MessaggioPosta)
@require_POST
def posta_carica(request):
    from . import assistente

    creati = []
    for f in request.FILES.getlist("file"):
        try:
            creati.append(crea_messaggio(f.read()))
        except assistente.AssistenteError as e:
            messages.error(request, f"{f.name}: {e}")
    if not creati:
        return redirect("posta")
    if assistente.configurato():
        for m in creati:
            try:
                assistente.elabora(m)
            except assistente.AssistenteError as e:
                messages.error(request, f"{m.oggetto}: {e}")
    messages.success(request, f"{len(creati)} mail caricate.")
    return redirect(creati[0] if len(creati) == 1 else "posta")


@login_required
def messaggio(request, pk):
    from . import assistente

    m = get_object_or_404(MessaggioPosta.objects.select_related("cliente", "produttore", "ordine", "ordine_acquisto"), pk=pk)
    return render(
        request,
        "ws/messaggio.html",
        {"m": m, "tipo": assistente.TIPI.get((m.analisi or {}).get("tipo"), ""), "configurato": assistente.configurato(), "stati": MessaggioPosta.Stato.choices},
    )


@richiede("change", MessaggioPosta)
@require_POST
def messaggio_analizza(request, pk):
    from . import assistente

    m = get_object_or_404(MessaggioPosta, pk=pk)
    if not assistente.configurato():
        messages.error(request, "L'assistente non è ancora configurato: manca la chiave API.")
    else:
        try:
            assistente.elabora(m)
            messages.success(request, "Mail analizzata.")
        except assistente.AssistenteError as e:
            messages.error(request, str(e))
    return redirect(m)


@richiede("change", MessaggioPosta)
@require_POST
def messaggio_applica(request, pk, indice):
    from . import assistente

    m = get_object_or_404(MessaggioPosta, pk=pk)
    proposta = (m.proposte or [None] * (indice + 1))[indice] if indice < len(m.proposte or []) else None
    if proposta and proposta.get("azione") == "registra_fattura" and not puo(request.user, "change", OrdineAcquisto):
        return _negato(request, m.get_absolute_url())
    try:
        assistente.applica(m, indice, request.user)
        messages.success(request, "Fatto.")
    except assistente.AssistenteError as e:
        messages.error(request, str(e))
    return redirect(m)


@richiede("change", MessaggioPosta)
@require_POST
def messaggio_stato(request, pk):
    m = get_object_or_404(MessaggioPosta, pk=pk)
    if request.POST.get("stato") in MessaggioPosta.Stato.values:
        m.stato = request.POST["stato"]
        m.save(update_fields=["stato"])
    return redirect(_next(request, m.get_absolute_url()))

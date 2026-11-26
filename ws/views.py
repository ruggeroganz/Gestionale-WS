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
from .ruoli import puo
from .models import (
    DDT,
    Artwork,
    Azienda,
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
    PreFattura,
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
    TestStabilita,
    VersioneFormula,
    VoceListino,
)

# Modelli modificabili dall'interfaccia con il form generico: nome -> (modello, campi)
CRUD = {
    "cliente": (Cliente, ["ragione_sociale", "tipo", "stato", "partita_iva", "codice_fiscale", "indirizzo", "cap", "comune", "provincia", "codice_paese", "paese", "codice_sdi", "pec", "pagamento", "email", "telefono", "commerciale", "note"]),
    "contatto": (Contatto, ["cliente", "nome", "ruolo", "email", "telefono"]),
    "produttore": (Produttore, ["nome", "paese", "indirizzo", "partita_iva", "lead_time_giorni", "email", "telefono", "note"]),
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
    "prodotto": (Prodotto, ["codice", "nome", "cliente", "progetto", "versione_formula", "formato", "prossima_consegna", "attivo"]),
    "rigadistinta": (RigaDistinta, ["prodotto", "packaging", "quantita_per_pezzo", "etichetta_correttiva"]),
    "movimento": (MovimentoPackaging, ["packaging", "produttore", "data", "tipo", "quantita", "note"]),
    "ordine": (OrdineCliente, ["cliente", "progetto", "produttore", "data", "data_consegna_prevista", "stato", "riferimento_cliente", "note"]),
    "rigaordine": (RigaOrdine, ["ordine", "prodotto", "quantita", "prezzo_unitario"]),
    "vocelistino": (VoceListino, ["produttore", "formula", "tipo", "descrizione", "quantita_minima", "costo_unitario", "prezzo_unitario", "valido_dal", "valido_fino", "note"]),
    "promemoria": (Promemoria, ["testo", "scadenza", "cliente", "progetto", "assegnato_a", "fatto"]),
    "azienda": (Azienda, ["ragione_sociale", "partita_iva", "codice_fiscale", "regime_fiscale", "indirizzo", "cap", "comune", "provincia", "codice_paese", "iban", "email", "telefono", "logo", "piede_documenti"]),
    "acquisto": (OrdineAcquisto, ["produttore", "ordine", "data", "data_consegna_richiesta", "stato", "ddt_fornitore", "fattura_fornitore", "importo_fattura_fornitore", "note"]),
    "rigaacquisto": (RigaAcquisto, ["ordine_acquisto", "tipo", "descrizione", "quantita", "costo_unitario"]),
    "ddt": (DDT, ["cliente", "ordine", "data", "luogo_partenza", "destinazione", "causale", "vettore", "porto", "colli", "peso_kg", "aspetto", "note"]),
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
        gruppi = [(nome, list(qs[:15])) for nome, qs in ricerche]
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
}


def crea_pdf(request, tipo, obj):
    """Restituisce (nome file, bytes) del documento impaginato sulla carta intestata."""
    from django.contrib.staticfiles import finders
    from django.template.loader import render_to_string
    from weasyprint import HTML

    _, template, variabile, nome = DOCUMENTI_PDF[tipo]
    az = Azienda.corrente()
    font = finders.find("ws/font/inter-latin-wght-normal.woff2")
    html = render_to_string(
        template,
        {
            variabile: obj,
            "righe": obj.righe.all(),
            "azienda": az,
            "base_template": "ws/pdf_base.html",
            "logo_url": f"file://{az.logo.path}" if az.pk and az.logo else "",
            "font_url": f"file://{font}" if font else "",
        },
        request=request,
    )
    return f"{nome(obj)}.pdf", HTML(string=html).write_pdf()


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

"""Regole di business: cancelli di fase, planner, coerenza INCI, fabbisogno packaging."""
import math
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum

from .models import (
    Artwork,
    Campionatura,
    Cliente,
    Evento,
    MovimentoPackaging,
    OrdineCliente,
    Packaging,
    Prodotto,
    Produttore,
    Progetto,
    Quotazione,
    RigaQuotazione,
    TestStabilita,
    VersioneFormula,
    oggi,
)

F = Progetto.Fase
FASI = list(F.values)
GIORNI_STABILITA = 90
GIORNI_CAMPIONATURA = 30
GIORNI_QUOTAZIONE = 15


class FlussoError(Exception):
    pass


@dataclass
class Controllo:
    ok: bool
    testo: str


def indice_fase(fase):
    return FASI.index(fase)


def fase_saltata(progetto, fase):
    """Con una formula esistente senza campionatura si passa dall'offerta direttamente alla fase successiva."""
    return fase == F.CAMPIONATURA and progetto.sviluppo == Progetto.Sviluppo.ESISTENTE


def fase_successiva(progetto_o_fase, progetto=None):
    """Fase che segue quella indicata (o quella corrente del progetto), saltando quelle non previste."""
    if isinstance(progetto_o_fase, Progetto):
        progetto, fase = progetto_o_fase, progetto_o_fase.fase
    else:
        fase = progetto_o_fase
    i = indice_fase(fase) + 1
    while i < len(FASI) and progetto is not None and fase_saltata(progetto, FASI[i]):
        i += 1
    return FASI[i] if i < len(FASI) else None


def richiede_stabilita(progetto):
    return progetto.sviluppo == Progetto.Sviluppo.NUOVA


def formula_approvata(progetto):
    """Formula su cui si lavora: quella dell'ultima campionatura approvata, o la formula esistente indicata."""
    c = progetto.campionature.filter(esito=Campionatura.Esito.APPROVATA).order_by("-numero").first()
    if c:
        return c.versione_formula
    if progetto.sviluppo != Progetto.Sviluppo.NUOVA:
        return progetto.versione_formula
    return None


def quotazione_accettata(progetto):
    return progetto.quotazioni.filter(stato=Quotazione.Stato.ACCETTATA).order_by("-numero").first()


def stabilita_superata(progetto, versione):
    return bool(versione) and progetto.stabilita.filter(
        versione_formula=versione, esito=TestStabilita.Esito.SUPERATA
    ).exists()


ORDINE_CONFERMATO = [
    OrdineCliente.Stato.ACCETTATA,
    OrdineCliente.Stato.IN_PRODUZIONE,
    OrdineCliente.Stato.PRONTO,
    OrdineCliente.Stato.CONSEGNATO,
]


def controlli(progetto):
    """Condizioni da soddisfare per uscire dalla fase corrente."""
    fase = progetto.fase
    va = formula_approvata(progetto)
    out = []
    if fase == F.LEAD:
        out.append(Controllo(progetto.produttore_id is not None, "Produttore assegnato al progetto"))
    elif fase == F.QUOTAZIONE:
        out.append(Controllo(quotazione_accettata(progetto) is not None, "Offerta accettata dal cliente"))
        if progetto.sviluppo == Progetto.Sviluppo.ESISTENTE:
            out.append(Controllo(va is not None, "Formula esistente indicata nei dati del progetto"))
    elif fase == F.CAMPIONATURA:
        out.append(Controllo(va is not None, "Campionatura approvata dal cliente"))
    elif fase == F.STABILITA:
        if richiede_stabilita(progetto):
            out.append(
                Controllo(stabilita_superata(progetto, va), f"Stabilità superata sulla formula approvata ({va or 'nessuna'})")
            )
        else:
            out.append(Controllo(va is not None, f"Formula esistente ({va or 'da indicare'}): stabilità non richiesta"))
        out.append(
            Controllo(
                progetto.ordini.filter(stato__in=ORDINE_CONFERMATO).exists(),
                "Ordine del cliente ricevuto e confermato",
            )
        )
        out.append(
            Controllo(
                bool(va)
                and progetto.artwork.filter(stato=Artwork.Stato.APPROVATO, versione_formula=va).exists(),
                "Artwork definitivo (approvato dal regolatorio) con l'INCI della formula",
            )
        )
        out.append(
            Controllo(
                bool(va)
                and progetto.prodotti.filter(versione_formula=va, distinta__isnull=False).exists(),
                "Prodotto (SKU) creato con distinta base e formula",
            )
        )
    elif fase == F.PACKAGING:
        out.append(
            Controllo(
                progetto.campione_packaging == Progetto.CampionePackaging.APPROVATO,
                "Campione di stampa del packaging approvato dal cliente",
            )
        )
    elif fase == F.PRODUZIONE:
        out.append(
            Controllo(
                progetto.ordini.filter(stato__in=[OrdineCliente.Stato.PRONTO, OrdineCliente.Stato.CONSEGNATO]).exists(),
                "Merce pronta comunicata dal produttore (stato dell'ordine)",
            )
        )
    elif fase == F.SPEDIZIONE:
        from .models import DDT, PreFattura

        fatture = PreFattura.objects.filter(ordine__progetto=progetto)
        out.append(Controllo(DDT.objects.filter(ordine__progetto=progetto).exists(), "DDT emesso"))
        out.append(
            Controllo(
                progetto.ordini.filter(stato=OrdineCliente.Stato.CONSEGNATO).exists(), "Ordine spedito al cliente"
            )
        )
        out.append(
            Controllo(
                fatture.exists() and not fatture.filter(numero_fattura="").exists(),
                "Fattura emessa (numero definitivo riportato sulla pre-fattura)",
            )
        )
        out.append(Controllo(fatture.exists() and not fatture.filter(pagata=False).exists(), "Pagamento ricevuto"))
    return out


@transaction.atomic
def avanza(progetto, utente=None):
    mancanti = [c.testo for c in controlli(progetto) if not c.ok]
    if mancanti:
        raise FlussoError("Non si può avanzare: " + "; ".join(mancanti))
    nuova = fase_successiva(progetto)
    if nuova is None:
        raise FlussoError("Il progetto è già nell'ultima fase.")
    vecchia = progetto.get_fase_display()
    progetto.fase = nuova
    if nuova == F.CONSEGNATO:
        progetto.stato = Progetto.Stato.CHIUSO
    progetto.save()
    testo = f"Fase: {vecchia} → {progetto.get_fase_display()}"
    if nuova == F.STABILITA and richiede_stabilita(progetto):
        va = formula_approvata(progetto)
        if not progetto.stabilita.filter(versione_formula=va).exclude(esito=TestStabilita.Esito.FALLITA).exists():
            t = TestStabilita.objects.create(progetto=progetto, versione_formula=va)
            testo += f". Avviata stabilità su {va}, fine prevista {t.data_fine_prevista:%d/%m/%Y}"
    if nuova == F.PACKAGING and progetto.cliente.stato == Cliente.Stato.POTENZIALE:
        progetto.cliente.stato = Cliente.Stato.ATTIVO
        progetto.cliente.save(update_fields=["stato"])
    Evento.objects.create(progetto=progetto, utente=utente, testo=testo, automatico=True)
    return progetto


@transaction.atomic
def riporta_a_fase(progetto, fase, motivo, utente=None):
    if indice_fase(fase) >= indice_fase(progetto.fase):
        raise FlussoError("Si può tornare solo a una fase precedente.")
    vecchia = progetto.get_fase_display()
    progetto.fase = fase
    progetto.save()
    Evento.objects.create(
        progetto=progetto,
        utente=utente,
        testo=f"Fase riportata: {vecchia} → {progetto.get_fase_display()}. Motivo: {motivo or 'non indicato'}",
        automatico=True,
    )


def progetto_di(obj):
    for percorso in ("progetto", "quotazione.progetto", "formula.progetto"):
        cur = obj
        for attr in percorso.split("."):
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if isinstance(cur, Progetto):
            return cur
    return None


@transaction.atomic
def dopo_salvataggio(obj, utente=None, creato=False):
    """Effetti collaterali del salvataggio di un record dall'interfaccia."""
    progetto = progetto_di(obj)
    extra = []

    if isinstance(obj, Quotazione) and obj.stato == Quotazione.Stato.ACCETTATA:
        obj.progetto.quotazioni.filter(stato=Quotazione.Stato.ACCETTATA).exclude(pk=obj.pk).update(
            stato=Quotazione.Stato.SUPERATA
        )

    if isinstance(obj, TestStabilita) and obj.esito == TestStabilita.Esito.FALLITA:
        n = (
            Artwork.objects.filter(progetto=obj.progetto, versione_formula=obj.versione_formula)
            .exclude(stato__in=[Artwork.Stato.SUPERATO, Artwork.Stato.DA_RIFARE])
            .update(stato=Artwork.Stato.DA_RIFARE)
        )
        if n:
            extra.append(f"{n} artwork segnati da rifare")
        if obj.progetto.fase in (F.STABILITA, F.PACKAGING):
            obj.progetto.fase = F.CAMPIONATURA
            obj.progetto.save()
            extra.append("progetto riportato in Campionatura: serve una nuova versione della formula")

    if isinstance(obj, VersioneFormula) and creato:
        prec = obj.precedente
        if prec and not obj.stesso_inci(prec):
            extra.append(f"INCI diverso da v{prec.numero}: verificare artwork, quotazione e giacenze di packaging")

    if isinstance(obj, OrdineCliente) and obj.stato in ORDINE_CONFERMATO:
        if obj.cliente.stato == Cliente.Stato.POTENZIALE:
            obj.cliente.stato = Cliente.Stato.ATTIVO
            obj.cliente.save(update_fields=["stato"])

    if progetto is not None:
        azione = "Aggiunto" if creato else "Aggiornato"
        testo = f"{azione} {obj._meta.verbose_name}: {obj}"
        stato = getattr(obj, "get_stato_display", None) or getattr(obj, "get_esito_display", None)
        if stato:
            testo += f" ({stato()})"
        if extra:
            testo += ". " + "; ".join(extra).capitalize()
        Evento.objects.create(progetto=progetto, utente=utente, testo=testo, automatico=True)


# --------------------------------------------------------------------------
# Planner a ritroso e scadenze
# --------------------------------------------------------------------------
GIORNI_SOLLECITO_TDS = 14
GIORNI_CAMPIONE_STAMPA = 105  # il campione di stampa arriva dopo 3-4 mesi dall'avvio del packaging
GIORNI_PREAVVISO_RIORDINO = 30


def planner(progetto):
    """Scadenze calcolate a ritroso dalla data di consegna richiesta."""
    consegna = progetto.data_consegna_richiesta
    if not consegna:
        return []
    lead = progetto.lead_time_giorni
    t_packaging = consegna - timedelta(days=lead)
    i = indice_fase(progetto.fase)
    tappe = []
    t_formula = t_packaging
    if richiede_stabilita(progetto):
        t_formula = t_packaging - timedelta(days=GIORNI_STABILITA)
    if progetto.sviluppo != Progetto.Sviluppo.ESISTENTE:
        t_offerta = t_formula - timedelta(days=GIORNI_CAMPIONATURA)
        tappe.append(("Offerta accettata, avvio campionature", t_offerta, i > indice_fase(F.QUOTAZIONE)))
        nome = "Formula approvata e avvio stabilità" if richiede_stabilita(progetto) else "Campionatura approvata"
        tappe.append((nome, t_formula, i > indice_fase(F.CAMPIONATURA)))
    else:
        tappe.append(("Offerta accettata", t_packaging - timedelta(days=GIORNI_QUOTAZIONE), i > indice_fase(F.QUOTAZIONE)))
    cosa = "Stabilità superata, ordine" if richiede_stabilita(progetto) else "Ordine"
    tappe.append(
        (f"{cosa} e artwork definitivo: avvio packaging (lead time {lead} gg)", t_packaging, i > indice_fase(F.STABILITA))
    )
    t_campione = min(consegna, t_packaging + timedelta(days=GIORNI_CAMPIONE_STAMPA))
    tappe.append(("Campione di stampa approvato dal cliente", t_campione, i > indice_fase(F.PACKAGING)))
    tappe.append(("Merce pronta, consegna richiesta dal cliente", consegna, i > indice_fase(F.PRODUZIONE)))
    today = oggi()
    return [
        {"nome": nome, "data": data, "fatto": fatto, "in_ritardo": not fatto and data < today}
        for nome, data, fatto in tappe
    ]


def in_ritardo(progetto):
    return any(t["in_ritardo"] for t in planner(progetto))


def tds_da_sollecitare(progetto=None):
    """Artwork fermi in attesa del TDS da più di due settimane."""
    qs = Artwork.objects.filter(
        stato=Artwork.Stato.ATTESA_TDS,
        data_tds_richiesto__isnull=False,
        data_tds_richiesto__lte=oggi() - timedelta(days=GIORNI_SOLLECITO_TDS),
    ).select_related("progetto", "cliente")
    return qs.filter(progetto=progetto) if progetto is not None else qs.exclude(progetto__stato=Progetto.Stato.CHIUSO)


def avvisi_progetto(progetto):
    out = []
    va = formula_approvata(progetto)
    q = quotazione_accettata(progetto)
    if va and q and q.versione_formula_id and q.versione_formula_id != va.pk:
        out.append(
            f"L'offerta accettata è riferita a {q.versione_formula}, ma la formula approvata è {va}: "
            "verificare se il prezzo va aggiornato."
        )
    for t in progetto.stabilita.all():
        if t.scaduta:
            out.append(f"Stabilità su {t.versione_formula} terminata il {t.data_fine_prevista:%d/%m/%Y}: registrare l'esito.")
    for a in progetto.artwork.filter(stato=Artwork.Stato.DA_RIFARE):
        out.append(f"Artwork «{a}» da rifare: l'INCI riportato non è più valido.")
    for a in tds_da_sollecitare(progetto):
        giorni = (oggi() - a.data_tds_richiesto).days
        out.append(f"TDS per «{a.nome}» richiesto {giorni} giorni fa e non ancora ricevuto: sollecitare il produttore.")
    for t in planner(progetto):
        if t["in_ritardo"]:
            out.append(f"In ritardo sul piano: «{t['nome']}» era prevista entro il {t['data']:%d/%m/%Y}.")
            break
    return out


def pagamenti_da_verificare(giorni=7):
    """Pre-fatture non ancora pagate con scadenza passata o entro pochi giorni."""
    from .models import PreFattura

    return (
        PreFattura.objects.filter(pagata=False, data_scadenza__isnull=False, data_scadenza__lte=oggi() + timedelta(days=giorni))
        .select_related("cliente")
        .order_by("data_scadenza")
    )


def riordini_da_sollecitare():
    """Prodotti con una consegna prevista e nessun ordine aperto: l'ordine serve un lead time prima."""
    aperti = [s for s in OrdineCliente.Stato.values if s not in ("consegnato", "annullato")]
    out = []
    prodotti = Prodotto.objects.filter(attivo=True, prossima_consegna__isnull=False).select_related("cliente", "progetto")
    for p in prodotti.exclude(righe_ordine__ordine__stato__in=aperti).distinct():
        lead = p.progetto.lead_time_giorni if p.progetto_id else 150
        entro = p.prossima_consegna - timedelta(days=lead)
        mancano = (entro - oggi()).days
        if mancano <= GIORNI_PREAVVISO_RIORDINO:
            out.append({"prodotto": p, "entro": entro, "mancano": mancano})
    out.sort(key=lambda r: r["entro"])
    return out


def fatture_produttore_diverse():
    from .models import OrdineAcquisto

    return [
        oa
        for oa in OrdineAcquisto.objects.filter(importo_fattura_fornitore__isnull=False)
        .select_related("produttore")
        .prefetch_related("righe")
        if oa.differenza_fattura is not None
    ]


# --------------------------------------------------------------------------
# Coerenza INCI tra formula da produrre e packaging già stampato
# --------------------------------------------------------------------------
def avvisi_inci(prodotto):
    """Righe di distinta il cui packaging riporta un INCI diverso dalla formula da produrre."""
    out = []
    attuale = prodotto.versione_formula
    for riga in prodotto.distinta.select_related("packaging__artwork__versione_formula__formula"):
        p = riga.packaging
        if not p.riporta_inci:
            continue
        if not p.artwork_id or not p.artwork.versione_formula_id:
            out.append({"riga": riga, "packaging": p, "tipo": "mancante", "giacenza": p.giacenza(), "risolto": False})
            continue
        stampata = p.artwork.versione_formula
        if attuale and stampata.pk != attuale.pk and not attuale.stesso_inci(stampata):
            out.append(
                {
                    "riga": riga,
                    "packaging": p,
                    "tipo": "diverso",
                    "stampata": stampata,
                    "attuale": attuale,
                    "giacenza": p.giacenza(),
                    "risolto": riga.etichetta_correttiva,
                }
            )
    return out


def tutti_avvisi_inci(solo_aperti=True):
    out = []
    prodotti = Prodotto.objects.filter(attivo=True).select_related("cliente", "versione_formula__formula")
    for prodotto in prodotti:
        for a in avvisi_inci(prodotto):
            if solo_aperti and a["risolto"]:
                continue
            a["prodotto"] = prodotto
            out.append(a)
    return out


# --------------------------------------------------------------------------
# Magazzino packaging e fabbisogno
# --------------------------------------------------------------------------
def giacenze(cliente=None):
    qs = MovimentoPackaging.objects.all()
    if cliente is not None:
        qs = qs.filter(packaging__cliente=cliente)
    righe = qs.values("packaging", "produttore").annotate(q=Sum("quantita")).order_by()
    pk_obsoleti = {a["packaging"].pk for a in tutti_avvisi_inci()}
    packaging = Packaging.objects.select_related("cliente", "componente", "artwork__versione_formula__formula").in_bulk(
        [r["packaging"] for r in righe]
    )
    produttori = Produttore.objects.in_bulk([r["produttore"] for r in righe])
    out = [
        {
            "packaging": packaging[r["packaging"]],
            "produttore": produttori[r["produttore"]],
            "quantita": r["q"],
            "inci_obsoleto": r["packaging"] in pk_obsoleti,
        }
        for r in righe
        if r["q"] != 0
    ]
    out.sort(key=lambda g: (g["packaging"].cliente.ragione_sociale, g["packaging"].codice))
    return out


def fabbisogno(ordine):
    """Packaging necessario per l'ordine, al netto della giacenza presso il produttore."""
    necessari = {}
    for riga in ordine.righe.select_related("prodotto"):
        for d in riga.prodotto.distinta.select_related("packaging"):
            q = math.ceil(riga.quantita * d.quantita_per_pezzo)
            necessari[d.packaging] = necessari.get(d.packaging, 0) + q
    out = []
    for p, q in necessari.items():
        giacenza = p.giacenza(ordine.produttore)
        mancante = max(0, q - giacenza)
        da_ordinare = max(mancante, p.moq or 0) if mancante else 0
        out.append(
            {
                "packaging": p,
                "necessari": q,
                "giacenza": giacenza,
                "mancante": mancante,
                "da_ordinare": da_ordinare,
                "residuo": giacenza + da_ordinare - q,
            }
        )
    out.sort(key=lambda r: r["packaging"].codice)
    return out


def piano_packaging(ordine):
    """Come fabbisogno(), ma se i movimenti sono già registrati ricostruisce la situazione di allora."""
    movimenti = list(ordine.movimenti.select_related("packaging"))
    if not movimenti:
        return fabbisogno(ordine)
    primo = min(m.pk for m in movimenti)
    per_packaging = {}
    for m in movimenti:
        d = per_packaging.setdefault(m.packaging, {"carico": 0, "consumo": 0})
        if m.tipo == MovimentoPackaging.Tipo.CARICO:
            d["carico"] += m.quantita
        elif m.tipo == MovimentoPackaging.Tipo.CONSUMO:
            d["consumo"] -= m.quantita
    out = []
    for p, d in per_packaging.items():
        prima = (
            MovimentoPackaging.objects.filter(packaging=p, produttore=ordine.produttore, pk__lt=primo).aggregate(
                q=Sum("quantita")
            )["q"]
            or 0
        )
        out.append(
            {
                "packaging": p,
                "necessari": d["consumo"],
                "giacenza": prima,
                "mancante": max(0, d["consumo"] - prima),
                "da_ordinare": d["carico"],
                "residuo": prima + d["carico"] - d["consumo"],
            }
        )
    out.sort(key=lambda r: r["packaging"].codice)
    return out


@transaction.atomic
def registra_packaging(ordine):
    """Carica il packaging acquistato dal produttore e scarica quello consumato dall'ordine."""
    if ordine.movimenti.exists():
        raise FlussoError("I movimenti di packaging per questo ordine sono già stati registrati.")
    righe = fabbisogno(ordine)
    if not righe:
        raise FlussoError("L'ordine non ha righe con distinta base.")
    for r in righe:
        comune = {"packaging": r["packaging"], "produttore": ordine.produttore, "ordine": ordine}
        if r["da_ordinare"]:
            MovimentoPackaging.objects.create(
                tipo=MovimentoPackaging.Tipo.CARICO,
                quantita=r["da_ordinare"],
                note=f"Acquisto per ordine {ordine.numero}",
                **comune,
            )
        MovimentoPackaging.objects.create(
            tipo=MovimentoPackaging.Tipo.CONSUMO,
            quantita=r["necessari"],
            note=f"Produzione ordine {ordine.numero}",
            **comune,
        )
    return righe


# --------------------------------------------------------------------------
# Listino storico
# --------------------------------------------------------------------------
def listino(testo=""):
    qs = (
        RigaQuotazione.objects.select_related(
            "quotazione__progetto__cliente", "quotazione__progetto__produttore", "quotazione__versione_formula__formula"
        )
        .exclude(quotazione__stato=Quotazione.Stato.BOZZA)
        .order_by("-quotazione__data", "-pk")
    )
    if testo:
        from django.db.models import Q

        qs = qs.filter(
            Q(descrizione__icontains=testo)
            | Q(quotazione__progetto__nome__icontains=testo)
            | Q(quotazione__progetto__tipo_prodotto__icontains=testo)
            | Q(quotazione__progetto__produttore__nome__icontains=testo)
            | Q(quotazione__versione_formula__formula__nome__icontains=testo)
            | Q(quotazione__versione_formula__formula__codice__icontains=testo)
        )
    return qs


# --------------------------------------------------------------------------
# Quotazioni: nuova versione, listino; riordini
# --------------------------------------------------------------------------
@transaction.atomic
def duplica_quotazione(quotazione):
    """Nuova versione in bozza con le stesse voci, da modificare."""
    nuova = Quotazione.objects.create(
        progetto=quotazione.progetto,
        versione_formula=formula_approvata(quotazione.progetto) or quotazione.versione_formula,
        valida_fino=None,
        note=quotazione.note,
    )
    for r in quotazione.righe.all():
        RigaQuotazione.objects.create(
            quotazione=nuova,
            tipo=r.tipo,
            descrizione=r.descrizione,
            quantita=r.quantita,
            costo_unitario=r.costo_unitario,
            prezzo_unitario=r.prezzo_unitario,
        )
    return nuova


def riga_in_listino(riga):
    from .models import VoceListino

    q = riga.quotazione
    if not q.progetto.produttore_id:
        raise FlussoError("Il progetto non ha un produttore: assegnalo prima di salvare la voce nel listino.")
    return VoceListino.objects.create(
        produttore=q.progetto.produttore,
        formula=q.versione_formula.formula if q.versione_formula_id else None,
        tipo=riga.tipo,
        descrizione=riga.descrizione,
        quantita_minima=riga.quantita,
        costo_unitario=riga.costo_unitario,
        prezzo_unitario=riga.prezzo_unitario,
        valido_dal=q.data,
        valido_fino=q.valida_fino,
        origine=riga,
    )


def voce_in_quotazione(voce, quotazione):
    return RigaQuotazione.objects.create(
        quotazione=quotazione,
        tipo=voce.tipo,
        descrizione=voce.descrizione,
        quantita=voce.quantita_minima,
        costo_unitario=voce.costo_unitario,
        prezzo_unitario=voce.prezzo_unitario,
    )


def voci_listino(testo="", scadute=False):
    from django.db.models import Q

    from .models import VoceListino

    qs = VoceListino.objects.select_related("produttore", "formula")
    if not scadute:
        qs = qs.filter(Q(valido_fino__isnull=True) | Q(valido_fino__gte=oggi()))
    if testo:
        qs = qs.filter(
            Q(descrizione__icontains=testo)
            | Q(produttore__nome__icontains=testo)
            | Q(formula__nome__icontains=testo)
            | Q(formula__codice__icontains=testo)
            | Q(note__icontains=testo)
        )
    return qs


@transaction.atomic
def crea_riordino(prodotto):
    """Ordine in bozza con quantità, prezzo e produttore dell'ultimo ordine del prodotto."""
    from .models import RigaOrdine

    ultima = (
        RigaOrdine.objects.filter(prodotto=prodotto)
        .exclude(ordine__stato=OrdineCliente.Stato.ANNULLATO)
        .select_related("ordine__produttore")
        .order_by("-ordine__data", "-pk")
        .first()
    )
    produttore = ultima.ordine.produttore if ultima else (prodotto.progetto.produttore if prodotto.progetto_id else None)
    if produttore is None:
        raise FlussoError("Non so a quale produttore assegnare il riordino: crea l'ordine a mano.")
    ordine = OrdineCliente.objects.create(
        cliente=prodotto.cliente, progetto=prodotto.progetto, produttore=produttore, note="Riordino."
    )
    RigaOrdine.objects.create(
        ordine=ordine,
        prodotto=prodotto,
        quantita=ultima.quantita if ultima else 1,
        prezzo_unitario=ultima.prezzo_unitario if ultima else 0,
    )
    return ordine

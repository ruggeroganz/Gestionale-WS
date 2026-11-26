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


def fase_successiva(fase):
    i = indice_fase(fase)
    return FASI[i + 1] if i + 1 < len(FASI) else None


def formula_approvata(progetto):
    """Versione della formula dell'ultima campionatura approvata dal cliente."""
    c = progetto.campionature.filter(esito=Campionatura.Esito.APPROVATA).order_by("-numero").first()
    return c.versione_formula if c else None


def quotazione_accettata(progetto):
    return progetto.quotazioni.filter(stato=Quotazione.Stato.ACCETTATA).order_by("-numero").first()


def stabilita_superata(progetto, versione):
    return bool(versione) and progetto.stabilita.filter(
        versione_formula=versione, esito=TestStabilita.Esito.SUPERATA
    ).exists()


def controlli(progetto):
    """Condizioni da soddisfare per uscire dalla fase corrente."""
    fase = progetto.fase
    va = formula_approvata(progetto)
    out = []
    if fase == F.LEAD:
        out.append(Controllo(progetto.produttore_id is not None, "Produttore assegnato al progetto"))
    elif fase == F.QUOTAZIONE:
        out.append(Controllo(quotazione_accettata(progetto) is not None, "Quotazione accettata dal cliente"))
    elif fase == F.CAMPIONATURA:
        out.append(Controllo(va is not None, "Campionatura approvata dal cliente"))
    elif fase == F.STABILITA:
        out.append(
            Controllo(
                stabilita_superata(progetto, va),
                f"Stabilità superata sulla formula approvata ({va or 'nessuna'})",
            )
        )
    elif fase == F.PACKAGING:
        out.append(
            Controllo(stabilita_superata(progetto, va), f"Stabilità superata sulla formula approvata ({va or 'nessuna'})")
        )
        out.append(
            Controllo(
                bool(va)
                and progetto.artwork.filter(stato=Artwork.Stato.APPROVATO, versione_formula=va).exists(),
                "Artwork approvato con l'INCI della formula approvata",
            )
        )
        out.append(
            Controllo(
                bool(va)
                and progetto.prodotti.filter(versione_formula=va, distinta__isnull=False).exists(),
                "Prodotto (SKU) creato con distinta base e formula approvata",
            )
        )
        out.append(Controllo(quotazione_accettata(progetto) is not None, "Quotazione accettata dal cliente"))
    elif fase == F.ORDINE:
        out.append(
            Controllo(
                progetto.ordini.filter(
                    stato__in=[
                        OrdineCliente.Stato.ACCETTATA,
                        OrdineCliente.Stato.IN_PRODUZIONE,
                        OrdineCliente.Stato.CONSEGNATO,
                    ]
                ).exists(),
                "Conferma d'ordine accettata dal cliente",
            )
        )
    elif fase == F.PRODUZIONE:
        out.append(
            Controllo(
                progetto.ordini.filter(stato=OrdineCliente.Stato.CONSEGNATO).exists(), "Ordine consegnato al cliente"
            )
        )
    return out


@transaction.atomic
def avanza(progetto, utente=None):
    mancanti = [c.testo for c in controlli(progetto) if not c.ok]
    if mancanti:
        raise FlussoError("Non si può avanzare: " + "; ".join(mancanti))
    nuova = fase_successiva(progetto.fase)
    if nuova is None:
        raise FlussoError("Il progetto è già nell'ultima fase.")
    vecchia = progetto.get_fase_display()
    progetto.fase = nuova
    if nuova == F.CONSEGNATO:
        progetto.stato = Progetto.Stato.CHIUSO
    progetto.save()
    testo = f"Fase: {vecchia} → {progetto.get_fase_display()}"
    if nuova == F.STABILITA:
        va = formula_approvata(progetto)
        if not progetto.stabilita.filter(versione_formula=va).exclude(esito=TestStabilita.Esito.FALLITA).exists():
            t = TestStabilita.objects.create(progetto=progetto, versione_formula=va)
            testo += f". Avviata stabilità su {va}, fine prevista {t.data_fine_prevista:%d/%m/%Y}"
    if nuova == F.ORDINE and progetto.cliente.stato == Cliente.Stato.POTENZIALE:
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

    if isinstance(obj, OrdineCliente) and obj.stato in (
        OrdineCliente.Stato.ACCETTATA,
        OrdineCliente.Stato.IN_PRODUZIONE,
        OrdineCliente.Stato.CONSEGNATO,
    ):
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
# Planner a ritroso
# --------------------------------------------------------------------------
def planner(progetto):
    """Scadenze calcolate a ritroso dalla data di consegna richiesta."""
    consegna = progetto.data_consegna_richiesta
    if not consegna:
        return []
    lead = progetto.produttore.lead_time_giorni if progetto.produttore_id else 150
    t_ordine = consegna - timedelta(days=lead)
    t_formula = t_ordine - timedelta(days=GIORNI_STABILITA)
    t_camp = t_formula - timedelta(days=GIORNI_CAMPIONATURA)
    t_quot = t_camp - timedelta(days=GIORNI_QUOTAZIONE)
    i = indice_fase(progetto.fase)
    tappe = [
        ("Quotazione accettata, avvio campionature", t_quot, i > indice_fase(F.QUOTAZIONE)),
        ("Formula approvata e avvio stabilità", t_formula, i > indice_fase(F.CAMPIONATURA)),
        (f"Stabilità superata ({GIORNI_STABILITA} gg)", t_ordine, i > indice_fase(F.STABILITA)),
        (f"Ordine definitivo e avvio packaging (lead time {lead} gg)", t_ordine, i > indice_fase(F.ORDINE)),
        ("Consegna richiesta dal cliente", consegna, i >= indice_fase(F.CONSEGNATO)),
    ]
    today = oggi()
    return [
        {"nome": nome, "data": data, "fatto": fatto, "in_ritardo": not fatto and data < today}
        for nome, data, fatto in tappe
    ]


def in_ritardo(progetto):
    return any(t["in_ritardo"] for t in planner(progetto))


def avvisi_progetto(progetto):
    out = []
    va = formula_approvata(progetto)
    q = quotazione_accettata(progetto)
    if va and q and q.versione_formula_id and q.versione_formula_id != va.pk:
        out.append(
            f"La quotazione accettata è riferita a {q.versione_formula}, ma la formula approvata è {va}: "
            "verificare se il prezzo va aggiornato."
        )
    for t in progetto.stabilita.all():
        if t.scaduta:
            out.append(f"Stabilità su {t.versione_formula} terminata il {t.data_fine_prevista:%d/%m/%Y}: registrare l'esito.")
    for a in progetto.artwork.filter(stato=Artwork.Stato.DA_RIFARE):
        out.append(f"Artwork «{a}» da rifare: l'INCI riportato non è più valido.")
    for t in planner(progetto):
        if t["in_ritardo"]:
            out.append(f"In ritardo sul piano: «{t['nome']}» era prevista entro il {t['data']:%d/%m/%Y}.")
            break
    return out


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

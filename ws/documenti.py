"""Documenti generati dall'ordine cliente: ordine d'acquisto, DDT, pre-fattura ed esportazioni."""
import csv
import io
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.db import transaction

from . import flusso
from .models import (
    DDT,
    Azienda,
    OrdineAcquisto,
    PreFattura,
    RigaAcquisto,
    RigaDDT,
    RigaPreFattura,
    Spedizione,
    Collo,
    TipoRiga,
    euro,
)

PAESI_UE = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE",
    "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}  # fmt: skip
NS_FATTURA = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"


def _righe_ordine(ordine):
    righe = list(ordine.righe.select_related("prodotto"))
    if not righe:
        raise flusso.FlussoError("L'ordine non ha righe: aggiungi prima i prodotti.")
    return righe


def _eccedenze(ordine):
    """Packaging acquistato oltre il necessario per questo ordine: resta in deposito, di proprietà del cliente."""
    return [(r, r["da_ordinare"] - r["mancante"]) for r in flusso.piano_packaging(ordine) if r["da_ordinare"] > r["mancante"]]


def _artwork_nuovi(ordine, campo):
    """Artwork del packaging in distinta i cui impianti non sono ancora stati ordinati / fatturati."""
    visti = {}
    for riga in ordine.righe.select_related("prodotto"):
        for d in riga.prodotto.distinta.select_related("packaging__artwork"):
            a = d.packaging.artwork
            if a is not None and not getattr(a, campo):
                visti[a.pk] = a
    return list(visti.values())


def _costo_prodotto(ordine):
    """Costo unitario del prodotto finito dalla quotazione accettata del progetto, se c'è."""
    if not ordine.progetto_id:
        return Decimal("0")
    q = flusso.quotazione_accettata(ordine.progetto)
    riga = q.righe.filter(tipo="prodotto").first() if q else None
    return riga.costo_unitario if riga else Decimal("0")


@transaction.atomic
def genera_ordine_acquisto(ordine):
    righe = _righe_ordine(ordine)
    oa = OrdineAcquisto.objects.create(
        produttore=ordine.produttore, ordine=ordine, data_consegna_richiesta=ordine.data_consegna_prevista
    )
    costo = _costo_prodotto(ordine)
    for r in righe:
        formula = f", formula {r.prodotto.versione_formula}" if r.prodotto.versione_formula_id else ""
        RigaAcquisto.objects.create(
            ordine_acquisto=oa,
            tipo=TipoRiga.PRODOTTO,
            descrizione=f"{r.prodotto.codice} · {r.prodotto.nome}{formula}"[:250],
            quantita=r.quantita,
            costo_unitario=costo,
        )
    for p, eccedenza in _eccedenze(ordine):
        k = p["packaging"]
        RigaAcquisto.objects.create(
            ordine_acquisto=oa,
            tipo=TipoRiga.PACKAGING,
            descrizione=f"{k.codice} · {k.descrizione}: eccedenza da tenere in deposito (acquisto totale {p['da_ordinare']} pz)"[:250],
            quantita=eccedenza,
            costo_unitario=k.costo_unitario or 0,
        )
    for a in _artwork_nuovi(ordine, "impianto_ordinato"):
        if a.costo_impianto:
            RigaAcquisto.objects.create(
                ordine_acquisto=oa,
                tipo=TipoRiga.IMPIANTI,
                descrizione=f"Impianti per nuovo artwork: {a}"[:250],
                quantita=1,
                costo_unitario=a.costo_impianto,
            )
        a.impianto_ordinato = True
        a.save(update_fields=["impianto_ordinato"])
    return oa


@transaction.atomic
def genera_ddt(ordine):
    righe = _righe_ordine(ordine)
    c = ordine.cliente
    ddt = DDT.objects.create(
        cliente=c,
        ordine=ordine,
        luogo_partenza=" · ".join(x for x in (ordine.produttore.nome, ordine.produttore.indirizzo) if x),
        destinazione=", ".join(x for x in (c.indirizzo, f"{c.cap} {c.comune}".strip(), c.provincia) if x),
        note=note_spedizione(ordine),
    )
    for r in righe:
        RigaDDT.objects.create(
            ddt=ddt,
            codice=r.prodotto.codice,
            descrizione=" · ".join(x for x in (r.prodotto.nome, r.prodotto.formato) if x),
            quantita=r.quantita,
            lotto=r.lotto,
        )
    return ddt


NOTA_LQ = "DANGEROUS GOODS {un} SHIPPED UNDER ADR EXEMPTION FOR LIMITED QUANTITIES ACCORDING TO ADR CHAPTER 3.4"


def note_spedizione(ordine):
    """Note standard per DDT e fattura: voce doganale e, se serve, dicitura merci pericolose in quantità limitata."""
    prodotti = [r.prodotto for r in ordine.righe.select_related("prodotto")]
    righe = [f"HS CODE {c}" for c in sorted({p.hs_code for p in prodotti if p.hs_code})]
    righe += [NOTA_LQ.format(un=u) for u in sorted({p.un_numero.replace(" ", "") for p in prodotti if p.un_numero and p.quantita_limitata})]
    return "\n".join(righe)


@transaction.atomic
def genera_spedizione(ordine):
    """Spedizione con un pallet per riga d'ordine, da suddividere e completare con pesi e dimensioni."""
    righe = _righe_ordine(ordine)
    c = ordine.cliente
    sp = Spedizione.objects.create(
        cliente=c,
        ordine=ordine,
        riferimenti=", ".join(f"DDT n. {d.numero}" for d in ordine.ddt.all()),
        destinazione=", ".join(x for x in (c.indirizzo, f"{c.cap} {c.comune}".strip(), c.paese) if x),
    )
    for r in righe:
        p = r.prodotto
        Collo.objects.create(
            spedizione=sp,
            prodotto=p,
            quantita=r.quantita,
            lotto=r.lotto,
            cartoni=-(-r.quantita // p.pezzi_per_cartone) if p.pezzi_per_cartone else None,
        )
    return sp


def iva_predefinita(cliente):
    paese = (cliente.codice_paese or "IT").upper()
    if paese == "IT":
        return Decimal("22"), ""
    return Decimal("0"), PreFattura.Natura.N3_2 if paese in PAESI_UE else PreFattura.Natura.N3_1


@transaction.atomic
def genera_prefattura(ordine):
    righe = _righe_ordine(ordine)
    aliquota, natura = iva_predefinita(ordine.cliente)
    pf = PreFattura.objects.create(
        cliente=ordine.cliente,
        ordine=ordine,
        ddt=ordine.ddt.order_by("-pk").first(),
        aliquota_iva=aliquota,
        natura=natura,
        pagamento=ordine.cliente.pagamento,
        note=note_spedizione(ordine),
    )
    for r in righe:
        RigaPreFattura.objects.create(
            prefattura=pf,
            tipo=TipoRiga.PRODOTTO,
            codice=r.prodotto.codice,
            descrizione=" · ".join(x for x in (r.prodotto.nome, r.prodotto.formato) if x),
            quantita=r.quantita,
            prezzo_unitario=r.prezzo_unitario,
        )
    for p, eccedenza in _eccedenze(ordine):
        k = p["packaging"]
        RigaPreFattura.objects.create(
            prefattura=pf,
            tipo=TipoRiga.PACKAGING,
            codice=k.codice,
            descrizione=f"{k.descrizione}: packaging di Vs. proprietà in deposito presso {ordine.produttore.nome}"[:250],
            quantita=eccedenza,
            prezzo_unitario=k.prezzo_unitario or 0,
        )
    for a in _artwork_nuovi(ordine, "impianto_fatturato"):
        if a.prezzo_impianto:
            RigaPreFattura.objects.create(
                prefattura=pf,
                tipo=TipoRiga.IMPIANTI,
                descrizione=f"Impianti per nuovo artwork: {a}"[:250],
                quantita=1,
                prezzo_unitario=a.prezzo_impianto,
            )
        a.impianto_fatturato = True
        a.save(update_fields=["impianto_fatturato"])
    return pf


# --------------------------------------------------------------------------
# Esportazioni della pre-fattura
# --------------------------------------------------------------------------
def controlli_prefattura(pf):
    """Dati mancanti che renderebbero il file non importabile."""
    a = Azienda.corrente()
    c = pf.cliente
    italiano = (c.codice_paese or "IT").upper() == "IT"
    out = []
    if not a.pk or not (a.partita_iva and a.indirizzo and a.cap and a.comune):
        out.append("Dati azienda incompleti (partita IVA, indirizzo, CAP, comune).")
    if not (c.partita_iva or c.codice_fiscale):
        out.append("Al cliente manca partita IVA o codice fiscale.")
    if not (c.indirizzo and c.comune and (c.cap or not italiano)):
        out.append("Al cliente manca l'indirizzo completo (via, CAP, comune).")
    if italiano and not (c.codice_sdi or c.pec):
        out.append("Al cliente manca il codice destinatario SDI o la PEC.")
    if not pf.righe.exists():
        out.append("La pre-fattura non ha righe.")
    if any(r.prezzo_unitario == 0 for r in pf.righe.all()):
        out.append("Ci sono righe con prezzo a zero.")
    if pf.aliquota_iva == 0 and not pf.natura:
        out.append("Con aliquota IVA 0 va indicata la natura.")
    if pf.aliquota_iva > 0 and pf.natura:
        out.append("La natura IVA va indicata solo con aliquota 0.")
    return out


def _el(padre, tag, testo=None):
    e = ET.SubElement(padre, tag)
    if testo is not None:
        # il tracciato ammette solo caratteri Latin-1: gli altri diventano "?"
        e.text = str(testo).encode("latin-1", "replace").decode("latin-1")
    return e


def _piva(valore, paese):
    v = (valore or "").replace(" ", "").upper()
    return v[2:] if v.startswith(paese) else v


def _anagrafica(padre, nome, partita_iva, codice_fiscale, paese, regime=None):
    dati = _el(padre, "DatiAnagrafici")
    if partita_iva:
        idf = _el(dati, "IdFiscaleIVA")
        _el(idf, "IdPaese", paese)
        _el(idf, "IdCodice", _piva(partita_iva, paese))
    if codice_fiscale and paese == "IT":
        _el(dati, "CodiceFiscale", codice_fiscale.replace(" ", "").upper())
    _el(_el(dati, "Anagrafica"), "Denominazione", nome[:80])
    if regime:
        _el(dati, "RegimeFiscale", regime)


def _sede(padre, indirizzo, cap, comune, provincia, paese):
    sede = _el(padre, "Sede")
    _el(sede, "Indirizzo", (indirizzo or "-")[:60])
    _el(sede, "CAP", cap if paese == "IT" and cap else "00000")
    _el(sede, "Comune", (comune or "-")[:60])
    if paese == "IT" and provincia:
        _el(sede, "Provincia", provincia.upper())
    _el(sede, "Nazione", paese)


def prefattura_xml(pf):
    """Pre-fattura in formato FatturaPA 1.2 (FPR12), lo standard della fattura elettronica."""
    a = Azienda.corrente()
    c = pf.cliente
    paese_a = (a.codice_paese or "IT").upper()
    paese_c = (c.codice_paese or "IT").upper()
    aliquota = f"{pf.aliquota_iva:.2f}"

    ET.register_namespace("p", NS_FATTURA)
    radice = ET.Element(f"{{{NS_FATTURA}}}FatturaElettronica", {"versione": "FPR12"})

    testata = _el(radice, "FatturaElettronicaHeader")
    trasm = _el(testata, "DatiTrasmissione")
    idt = _el(trasm, "IdTrasmittente")
    _el(idt, "IdPaese", paese_a)
    _el(idt, "IdCodice", _piva(a.partita_iva or a.codice_fiscale, paese_a) or "00000000000")
    _el(trasm, "ProgressivoInvio", f"{pf.pk:05d}")
    _el(trasm, "FormatoTrasmissione", "FPR12")
    _el(trasm, "CodiceDestinatario", (c.codice_sdi or "0000000").upper() if paese_c == "IT" else "XXXXXXX")
    if paese_c == "IT" and not c.codice_sdi and c.pec:
        _el(trasm, "PECDestinatario", c.pec)

    cedente = _el(testata, "CedentePrestatore")
    _anagrafica(cedente, a.ragione_sociale, a.partita_iva, a.codice_fiscale, paese_a, a.regime_fiscale or "RF01")
    _sede(cedente, a.indirizzo, a.cap, a.comune, a.provincia, paese_a)
    cessionario = _el(testata, "CessionarioCommittente")
    _anagrafica(cessionario, c.ragione_sociale, c.partita_iva, c.codice_fiscale, paese_c)
    _sede(cessionario, c.indirizzo, c.cap, c.comune, c.provincia, paese_c)

    corpo = _el(radice, "FatturaElettronicaBody")
    generali = _el(corpo, "DatiGenerali")
    doc = _el(generali, "DatiGeneraliDocumento")
    _el(doc, "TipoDocumento", "TD01")
    _el(doc, "Divisa", "EUR")
    _el(doc, "Data", (pf.data_fattura or pf.data).isoformat())
    _el(doc, "Numero", (pf.numero_fattura or pf.numero)[:20])
    _el(doc, "ImportoTotaleDocumento", f"{pf.totale:.2f}")
    if pf.note:
        _el(doc, "Causale", " ".join(pf.note.split())[:200])
    if pf.ordine_id and pf.ordine.riferimento_cliente:
        _el(_el(generali, "DatiOrdineAcquisto"), "IdDocumento", pf.ordine.riferimento_cliente[:20])
    if pf.ddt_id:
        ddt = _el(generali, "DatiDDT")
        _el(ddt, "NumeroDDT", pf.ddt.numero)
        _el(ddt, "DataDDT", pf.ddt.data.isoformat())

    beni = _el(corpo, "DatiBeniServizi")
    for n, r in enumerate(pf.righe.all(), 1):
        linea = _el(beni, "DettaglioLinee")
        _el(linea, "NumeroLinea", n)
        if r.codice:
            cod = _el(linea, "CodiceArticolo")
            _el(cod, "CodiceTipo", "INTERNO")
            _el(cod, "CodiceValore", r.codice[:35])
        _el(linea, "Descrizione", r.descrizione)
        _el(linea, "Quantita", f"{r.quantita:.2f}")
        _el(linea, "UnitaMisura", "PZ")
        _el(linea, "PrezzoUnitario", f"{r.prezzo_unitario:.4f}")
        _el(linea, "PrezzoTotale", f"{r.totale:.2f}")
        _el(linea, "AliquotaIVA", aliquota)
        if pf.natura:
            _el(linea, "Natura", pf.natura)
    riepilogo = _el(beni, "DatiRiepilogo")
    _el(riepilogo, "AliquotaIVA", aliquota)
    if pf.natura:
        _el(riepilogo, "Natura", pf.natura)
    _el(riepilogo, "ImponibileImporto", f"{pf.imponibile:.2f}")
    _el(riepilogo, "Imposta", f"{pf.imposta:.2f}")
    if pf.natura:
        _el(riepilogo, "RiferimentoNormativo", pf.get_natura_display().split(" · ", 1)[-1])
    else:
        _el(riepilogo, "EsigibilitaIVA", "I")

    if pf.data_scadenza:
        pagamento = _el(corpo, "DatiPagamento")
        _el(pagamento, "CondizioniPagamento", "TP02")
        dettaglio = _el(pagamento, "DettaglioPagamento")
        _el(dettaglio, "ModalitaPagamento", "MP05")
        _el(dettaglio, "DataScadenzaPagamento", pf.data_scadenza.isoformat())
        _el(dettaglio, "ImportoPagamento", f"{pf.totale:.2f}")
        if a.iban:
            _el(dettaglio, "IBAN", a.iban.replace(" ", "").upper())

    ET.indent(radice)
    return ET.tostring(radice, encoding="utf-8", xml_declaration=True)


def nome_file_xml(pf):
    a = Azienda.corrente()
    paese = (a.codice_paese or "IT").upper()
    return f"{paese}{_piva(a.partita_iva, paese) or '00000000000'}_{pf.pk:05d}.xml"


def prefattura_csv(pf):
    """Stesse informazioni in CSV (separatore punto e virgola, decimali con la virgola)."""
    c = pf.cliente
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(
        ["numero", "data", "cliente", "partita_iva", "codice_fiscale", "riga", "tipo", "codice", "descrizione",
         "quantita", "prezzo_unitario", "imponibile", "aliquota_iva", "natura_iva", "imposta", "pagamento",
         "scadenza", "ordine_cliente", "ddt"]
    )  # fmt: skip

    def num(v, cifre):
        return f"{v:.{cifre}f}".replace(".", ",")

    for n, r in enumerate(pf.righe.all(), 1):
        w.writerow(
            [pf.numero_fattura or pf.numero, (pf.data_fattura or pf.data).strftime("%d/%m/%Y"), c.ragione_sociale,
             c.partita_iva, c.codice_fiscale, n, r.tipo, r.codice, r.descrizione, r.quantita,
             num(r.prezzo_unitario, 4), num(r.totale, 2), num(pf.aliquota_iva, 2), pf.natura,
             num(euro(r.totale * pf.aliquota_iva / 100), 2), pf.pagamento,
             pf.data_scadenza.strftime("%d/%m/%Y") if pf.data_scadenza else "",
             pf.ordine.riferimento_cliente or pf.ordine.numero if pf.ordine_id else "",
             pf.ddt.numero if pf.ddt_id else ""]
        )  # fmt: skip
    return ("﻿" + out.getvalue()).encode("utf-8")

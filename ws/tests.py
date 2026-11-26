from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import brief as modulo_brief
from . import documenti, flusso
from .ruoli import AMMINISTRAZIONE, COMMERCIALE, CUSTOMER
from .models import (
    DDT,
    Artwork,
    Azienda,
    Campionatura,
    Cliente,
    Componente,
    Formula,
    MovimentoPackaging,
    OrdineAcquisto,
    OrdineCliente,
    Packaging,
    PreFattura,
    Prodotto,
    Produttore,
    Progetto,
    Quotazione,
    RigaDistinta,
    RigaOrdine,
    TestStabilita,
    VersioneFormula,
    oggi,
)
from .views import CRUD

INCI_1 = "Aqua, Glycerin, Parfum"
INCI_2 = "Aqua, Glycerin, Panthenol, Parfum"


class Base(TestCase):
    def setUp(self):
        self.produttore = Produttore.objects.create(nome="Terzista")
        self.cliente = Cliente.objects.create(ragione_sociale="Cliente")
        self.progetto = Progetto.objects.create(nome="Mousse", cliente=self.cliente)
        self.formula = Formula.objects.create(codice="F1", nome="Mousse", progetto=self.progetto)
        self.v1 = VersioneFormula.objects.create(formula=self.formula, inci=INCI_1)

    def prodotto_con_bombola(self, moq=20000):
        artwork = Artwork.objects.create(
            cliente=self.cliente, progetto=self.progetto, nome="Lito", versione_formula=self.v1, stato="approvato"
        )
        comp = Componente.objects.create(codice="BOM", tipo="bombola", descrizione="Bombola")
        pack = Packaging.objects.create(
            cliente=self.cliente, componente=comp, descrizione="Bombola lito", artwork=artwork, riporta_inci=True, moq=moq
        )
        prodotto = Prodotto.objects.create(
            codice="SKU1", nome="Mousse", cliente=self.cliente, progetto=self.progetto, versione_formula=self.v1
        )
        riga = RigaDistinta.objects.create(prodotto=prodotto, packaging=pack)
        return prodotto, pack, riga


class FlussoProgettoTest(Base):
    def test_codici_e_versioni_automatici(self):
        self.assertRegex(self.progetto.codice, r"^PRJ-\d{4}-001$")
        self.assertEqual(Progetto.objects.create(nome="B", cliente=self.cliente).codice[-3:], "002")
        self.assertEqual(self.v1.numero, 1)
        self.assertEqual(VersioneFormula.objects.create(formula=self.formula, inci=INCI_2).numero, 2)

    def test_percorso_completo_con_cancelli(self):
        p = self.progetto
        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)  # manca il produttore
        p.produttore = self.produttore
        p.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "quotazione")

        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)
        Quotazione.objects.create(progetto=p, versione_formula=self.v1, stato="accettata")
        flusso.avanza(p)
        self.assertEqual(p.fase, "campionatura")

        Campionatura.objects.create(progetto=p, versione_formula=self.v1, esito="modifiche")
        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)
        Campionatura.objects.create(progetto=p, versione_formula=self.v1, esito="approvata")
        flusso.avanza(p)
        self.assertEqual(p.fase, "stabilita")
        test = p.stabilita.get()  # avviata in automatico
        self.assertEqual(test.data_fine_prevista, oggi() + timedelta(days=90))

        # durante la stabilità arrivano ordine e artwork, ma il packaging non parte finché non è superata
        prodotto, _, _ = self.prodotto_con_bombola()
        ordine = OrdineCliente.objects.create(cliente=self.cliente, progetto=p, produttore=self.produttore, stato="accettata")
        RigaOrdine.objects.create(ordine=ordine, prodotto=prodotto, quantita=5000, prezzo_unitario="2.75")
        mancanti = [c.testo for c in flusso.controlli(p) if not c.ok]
        self.assertEqual(len(mancanti), 1)
        self.assertIn("Stabilità", mancanti[0])
        test.esito = "superata"
        test.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "packaging")
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.stato, "attivo")

        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)  # serve il campione di stampa approvato
        p.campione_packaging = "approvato"
        p.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "produzione")

        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)
        ordine.stato = "pronto"
        ordine.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "spedizione")

        documenti.genera_ddt(ordine)
        pf = documenti.genera_prefattura(ordine)
        ordine.stato = "consegnato"
        ordine.save()
        self.assertEqual([c.ok for c in flusso.controlli(p)], [True, True, False, False])
        pf.numero_fattura, pf.pagata = "12/2026", True
        pf.save()
        flusso.avanza(p)
        self.assertEqual((p.fase, p.stato), ("consegnato", "chiuso"))

    def test_formula_esistente_salta_campionatura_e_stabilita(self):
        p = self.progetto
        p.produttore, p.fase, p.sviluppo = self.produttore, "quotazione", "esistente"
        p.save()
        Quotazione.objects.create(progetto=p, stato="accettata")
        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)  # va indicata la formula esistente
        p.versione_formula = self.v1
        p.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "stabilita")  # la campionatura è saltata
        self.assertFalse(p.stabilita.exists())  # e nessun test di stabilità parte
        self.assertEqual(flusso.formula_approvata(p), self.v1)
        testi = [c.testo for c in flusso.controlli(p)]
        self.assertTrue(any("stabilità non richiesta" in t for t in testi))
        self.assertEqual(len(flusso.planner(p)), 0)
        p.data_consegna_richiesta = oggi() + timedelta(days=200)
        self.assertEqual([t["nome"][:7] for t in flusso.planner(p)], ["Offerta", "Ordine ", "Campion", "Merce p"])

    def test_tds_da_sollecitare(self):
        a = Artwork.objects.create(cliente=self.cliente, progetto=self.progetto, nome="Lito", stato="attesa_tds", data_tds_richiesto=oggi() - timedelta(days=5))
        self.assertFalse(any("TDS" in x for x in flusso.avvisi_progetto(self.progetto)))
        a.data_tds_richiesto = oggi() - timedelta(days=20)
        a.save()
        self.assertTrue(any("sollecitare il produttore" in x for x in flusso.avvisi_progetto(self.progetto)))
        self.assertIn(a, flusso.tds_da_sollecitare())

    def test_stabilita_fallita_riporta_in_campionatura(self):
        p = self.progetto
        p.fase = "packaging"
        p.save()
        artwork = Artwork.objects.create(cliente=self.cliente, progetto=p, nome="Lito", versione_formula=self.v1, stato="approvato")
        test = TestStabilita.objects.create(progetto=p, versione_formula=self.v1, esito="fallita")
        flusso.dopo_salvataggio(test)
        p.refresh_from_db()
        artwork.refresh_from_db()
        self.assertEqual(p.fase, "campionatura")
        self.assertEqual(artwork.stato, "da_rifare")

    def test_una_sola_quotazione_accettata(self):
        q1 = Quotazione.objects.create(progetto=self.progetto, stato="accettata")
        q2 = Quotazione.objects.create(progetto=self.progetto, stato="accettata")
        flusso.dopo_salvataggio(q2)
        q1.refresh_from_db()
        self.assertEqual(q1.stato, "superata")
        self.assertEqual(flusso.quotazione_accettata(self.progetto), q2)

    def test_avviso_quotazione_su_formula_diversa(self):
        v2 = VersioneFormula.objects.create(formula=self.formula, inci=INCI_2)
        Quotazione.objects.create(progetto=self.progetto, versione_formula=self.v1, stato="accettata")
        Campionatura.objects.create(progetto=self.progetto, versione_formula=v2, esito="approvata")
        self.assertTrue(any("prezzo" in a for a in flusso.avvisi_progetto(self.progetto)))

    def test_planner_a_ritroso(self):
        p = self.progetto
        p.lead_time_giorni = 120
        p.data_consegna_richiesta = oggi() + timedelta(days=100)  # meno di 120 + 90 giorni
        p.save()
        tappe = flusso.planner(p)
        self.assertEqual(tappe[-1]["data"], p.data_consegna_richiesta)
        self.assertEqual(tappe[1]["data"], p.data_consegna_richiesta - timedelta(days=210))  # formula approvata
        self.assertEqual(tappe[2]["data"], p.data_consegna_richiesta - timedelta(days=120))  # avvio packaging
        self.assertTrue(flusso.in_ritardo(p))

    def test_prezzo_suggerito_e_margine_netto(self):
        from decimal import Decimal as D

        q = Quotazione.objects.create(progetto=self.progetto, commissione_pct=D("5"), margine_obiettivo_pct=D("25"))
        r = q.righe.create(descrizione="Mousse", quantita=1000, costo_unitario=D("1.30"), costi_fissi=D("0.10"))
        # (1,30 + 0,10) / (1 - 0,25 - 0,05) = 2,00: il prezzo lasciato a zero viene proposto
        self.assertEqual(r.prezzo_unitario, D("2.000"))
        self.assertEqual(r.commissione_unitaria, D("0.1"))
        self.assertEqual(r.margine_unitario, D("0.5"))
        self.assertEqual(r.margine_pct, 25)
        self.assertEqual(q.margine_pct, 25)
        r.prezzo_unitario = D("1.80")  # trattativa: si scende di prezzo
        r.save()
        self.assertEqual(r.prezzo_unitario, D("1.80"))
        self.assertAlmostEqual(float(r.margine_pct), 17.22, places=2)


class InciEMagazzinoTest(Base):
    def test_inci_non_allineato_e_soluzioni(self):
        prodotto, pack, riga = self.prodotto_con_bombola()
        MovimentoPackaging.objects.create(packaging=pack, produttore=self.produttore, tipo="carico", quantita=15000)
        self.assertEqual(flusso.avvisi_inci(prodotto), [])

        # stessa lista ingredienti scritta diversamente: nessun conflitto
        prodotto.versione_formula = VersioneFormula.objects.create(formula=self.formula, inci="aqua,  glycerin , PARFUM")
        prodotto.save()
        self.assertEqual(flusso.avvisi_inci(prodotto), [])

        prodotto.versione_formula = VersioneFormula.objects.create(formula=self.formula, inci=INCI_2)
        prodotto.save()
        (avviso,) = flusso.avvisi_inci(prodotto)
        self.assertEqual((avviso["tipo"], avviso["giacenza"], avviso["risolto"]), ("diverso", 15000, False))
        self.assertEqual(len(flusso.tutti_avvisi_inci()), 1)
        self.assertTrue(flusso.giacenze()[0]["inci_obsoleto"])

        riga.etichetta_correttiva = True
        riga.save()
        self.assertTrue(flusso.avvisi_inci(prodotto)[0]["risolto"])
        self.assertEqual(flusso.tutti_avvisi_inci(), [])

    def test_fabbisogno_moq_e_residuo(self):
        prodotto, pack, _ = self.prodotto_con_bombola(moq=20000)
        ordine = OrdineCliente.objects.create(cliente=self.cliente, produttore=self.produttore)
        RigaOrdine.objects.create(ordine=ordine, prodotto=prodotto, quantita=5000)
        (f,) = flusso.fabbisogno(ordine)
        self.assertEqual((f["necessari"], f["da_ordinare"], f["residuo"]), (5000, 20000, 15000))

        flusso.registra_packaging(ordine)
        self.assertEqual(pack.giacenza(self.produttore), 15000)
        with self.assertRaises(flusso.FlussoError):
            flusso.registra_packaging(ordine)

        # riordino: 10.000 pezzi coperti dal residuo, nessun nuovo acquisto
        riordino = OrdineCliente.objects.create(cliente=self.cliente, produttore=self.produttore)
        RigaOrdine.objects.create(ordine=riordino, prodotto=prodotto, quantita=10000)
        (f,) = flusso.fabbisogno(riordino)
        self.assertEqual((f["giacenza"], f["da_ordinare"], f["residuo"]), (15000, 0, 5000))

        # la giacenza presso un altro produttore non conta
        altro = Produttore.objects.create(nome="Altro")
        riordino.produttore = altro
        riordino.save()
        self.assertEqual(flusso.fabbisogno(riordino)[0]["da_ordinare"], 20000)

    def test_segno_dei_movimenti(self):
        _, pack, _ = self.prodotto_con_bombola()
        for tipo, q in (("carico", 100), ("consumo", 30), ("scarto", 20), ("rettifica", -5)):
            MovimentoPackaging.objects.create(packaging=pack, produttore=self.produttore, tipo=tipo, quantita=q)
        self.assertEqual(pack.giacenza(), 45)


class PagineTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("dati_demo", verbosity=0)

    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username="admin"))

    def test_login_obbligatorio(self):
        self.client.logout()
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, "/accedi/?next=/")

    def test_tutte_le_pagine_si_aprono(self):
        urls = [reverse(n) for n in ("dashboard", "progetti", "clienti", "produttori", "formule", "prodotti", "catalogo", "magazzino", "listino", "ordini", "acquisti", "ddt_elenco", "prefatture", "cerca")]
        urls += [reverse("cerca") + "?q=mousse", reverse("listino") + "?scadute=1"]
        urls += [reverse("quotazione_stampa", args=[q.pk]) for q in Quotazione.objects.all()]
        urls.append(reverse("listino") + f"?quotazione={Quotazione.objects.first().pk}")
        urls.append(reverse("listino") + "?q=mousse")
        urls.append(reverse("progetti") + "?stato=tutti")
        urls += [p.get_absolute_url() for p in Progetto.objects.all()]
        urls += [c.get_absolute_url() for c in Cliente.objects.all()]
        urls += [p.get_absolute_url() for p in Prodotto.objects.all()]
        for o in OrdineCliente.objects.all():
            urls += [o.get_absolute_url(), reverse("ordine_stampa", args=[o.pk])]
        from .models import Brief

        urls += [b.get_absolute_url() for b in Brief.objects.all()]
        from .models import Spedizione

        urls.append(reverse("spedizioni"))
        for sp in Spedizione.objects.all():
            urls += [sp.get_absolute_url(), reverse("pdf", args=["packing", sp.pk]), reverse("pdf", args=["multimodale", sp.pk])]
        for modello in (OrdineAcquisto, DDT, PreFattura):
            urls += [d.get_absolute_url() for d in modello.objects.all()]
        for nome, (modello, _) in CRUD.items():
            urls.append(reverse("nuovo", args=[nome]))
            primo = modello.objects.first()
            if primo:
                urls.append(reverse("modifica", args=[nome, primo.pk]))
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_demo_mostra_il_conflitto_inci(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "LUM-MOU-200")
        bozza = OrdineCliente.objects.get(stato="bozza")
        r = self.client.get(bozza.get_absolute_url())
        self.assertContains(r, "INCI non allineato")
        self.assertContains(r, "coperto")

    def test_form_generico_crea_e_registra_evento(self):
        p = Progetto.objects.get(nome__startswith="Deodorante")
        q = p.quotazioni.get()
        url = reverse("modifica", args=["quotazione", q.pk]) + f"?next={p.get_absolute_url()}"
        r = self.client.post(url, {"progetto": p.pk, "data": q.data.isoformat(), "stato": "accettata", "commissione_pct": "0", "next": p.get_absolute_url()})
        self.assertRedirects(r, p.get_absolute_url())
        self.assertTrue(p.eventi.filter(testo__contains="Accettata").exists())
        r = self.client.post(reverse("progetto_avanza", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.fase, "campionatura")

    def test_nuova_campionatura_propone_solo_formule_del_progetto(self):
        p = Progetto.objects.get(nome__startswith="Shampoo")
        r = self.client.get(reverse("nuovo", args=["campionatura"]) + f"?progetto={p.pk}")
        scelte = list(r.context["form"].fields["versione_formula"].queryset)
        self.assertEqual({v.formula.progetto for v in scelte}, {p})


class DocumentiTest(Base):
    def setUp(self):
        super().setUp()
        self.progetto.produttore = self.produttore
        self.progetto.save()
        self.cliente.partita_iva, self.cliente.indirizzo, self.cliente.cap = "IT01234567890", "Via Roma 1", "20100"
        self.cliente.comune, self.cliente.provincia, self.cliente.codice_sdi = "Milano", "MI", "ABC1234"
        self.cliente.save()
        Azienda.objects.create(ragione_sociale="WS Srl", partita_iva="09876543210", indirizzo="Via A 1", cap="20100", comune="Milano", provincia="MI")
        self.prodotto, self.pack, _ = self.prodotto_con_bombola(moq=20000)
        self.pack.costo_unitario, self.pack.prezzo_unitario = "0.4200", "0.4800"
        self.pack.save()
        q = Quotazione.objects.create(progetto=self.progetto, stato="accettata")
        q.righe.create(tipo="prodotto", descrizione="Mousse", quantita=5000, costo_unitario="1.85", prezzo_unitario="2.75")
        self.ordine = OrdineCliente.objects.create(cliente=self.cliente, progetto=self.progetto, produttore=self.produttore, riferimento_cliente="PO-1")
        RigaOrdine.objects.create(ordine=self.ordine, prodotto=self.prodotto, quantita=5000, prezzo_unitario="2.75")

    def test_ordine_acquisto_con_eccedenza_packaging(self):
        oa = documenti.genera_ordine_acquisto(self.ordine)
        prodotto, packaging = oa.righe.all()
        self.assertEqual((prodotto.quantita, str(prodotto.costo_unitario)), (5000, "1.8500"))
        self.assertEqual((packaging.tipo, packaging.quantita, str(packaging.costo_unitario)), ("packaging", 15000, "0.4200"))
        self.assertEqual(oa.totale, 5000 * 1.85 + 15000 * 0.42)
        self.assertRegex(oa.numero, r"^OA-\d{4}-001$")

    def test_documenti_uguali_prima_e_dopo_la_registrazione_del_magazzino(self):
        prima = [(r.quantita, r.prezzo_unitario) for r in documenti.genera_prefattura(self.ordine).righe.all()]
        flusso.registra_packaging(self.ordine)
        dopo = [(r.quantita, r.prezzo_unitario) for r in documenti.genera_prefattura(self.ordine).righe.all()]
        self.assertEqual(prima, dopo)
        self.assertEqual([q for q, _ in dopo], [5000, 15000])

    def test_riordino_coperto_dalla_giacenza_non_rifattura_packaging(self):
        flusso.registra_packaging(self.ordine)
        riordino = OrdineCliente.objects.create(cliente=self.cliente, produttore=self.produttore)
        RigaOrdine.objects.create(ordine=riordino, prodotto=self.prodotto, quantita=8000, prezzo_unitario="2.65")
        self.assertEqual([r.tipo for r in documenti.genera_prefattura(riordino).righe.all()], ["prodotto"])
        self.assertEqual(documenti.genera_ordine_acquisto(riordino).righe.count(), 1)

    def test_ddt(self):
        ddt = documenti.genera_ddt(self.ordine)
        self.assertEqual(ddt.destinazione, "Via Roma 1, 20100 Milano, MI")
        self.assertEqual([(r.codice, r.quantita) for r in ddt.righe.all()], [("SKU1", 5000)])

    def test_prefattura_totali_e_xml(self):
        import xml.etree.ElementTree as ET

        ddt = documenti.genera_ddt(self.ordine)
        pf = documenti.genera_prefattura(self.ordine)
        self.assertEqual(pf.ddt, ddt)
        self.assertEqual((str(pf.imponibile), str(pf.imposta), str(pf.totale)), ("20950.00", "4609.00", "25559.00"))
        self.assertEqual(documenti.controlli_prefattura(pf), [])

        radice = ET.fromstring(documenti.prefattura_xml(pf))
        self.assertEqual(radice.tag, "{http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2}FatturaElettronica")
        t = lambda percorso: radice.findtext(percorso)  # noqa: E731
        self.assertEqual(t("FatturaElettronicaHeader/DatiTrasmissione/CodiceDestinatario"), "ABC1234")
        self.assertEqual(t("FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdCodice"), "09876543210")
        self.assertEqual(t("FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA/IdCodice"), "01234567890")
        corpo = "FatturaElettronicaBody/"
        self.assertEqual(t(corpo + "DatiGenerali/DatiGeneraliDocumento/Numero"), pf.numero)
        self.assertEqual(t(corpo + "DatiGenerali/DatiOrdineAcquisto/IdDocumento"), "PO-1")
        self.assertEqual(t(corpo + "DatiGenerali/DatiDDT/NumeroDDT"), ddt.numero)
        linee = radice.findall(corpo + "DatiBeniServizi/DettaglioLinee")
        self.assertEqual([l.findtext("PrezzoTotale") for l in linee], ["13750.00", "7200.00"])
        self.assertEqual(t(corpo + "DatiBeniServizi/DatiRiepilogo/ImponibileImporto"), "20950.00")
        self.assertEqual(t(corpo + "DatiBeniServizi/DatiRiepilogo/Imposta"), "4609.00")
        self.assertEqual(t(corpo + "DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento"), "25559.00")

        righe_csv = documenti.prefattura_csv(pf).decode("utf-8-sig").splitlines()
        self.assertEqual(len(righe_csv), 3)
        self.assertIn(";13750,00;22,00;", righe_csv[1])

    def test_cliente_estero_senza_iva(self):
        self.cliente.codice_paese, self.cliente.partita_iva = "SE", "SE556000000001"
        self.cliente.save()
        pf = documenti.genera_prefattura(self.ordine)
        self.assertEqual((pf.aliquota_iva, pf.natura, pf.imposta), (0, "N3.2", 0))
        xml = documenti.prefattura_xml(pf).decode()
        self.assertIn("<CodiceDestinatario>XXXXXXX</CodiceDestinatario>", xml)
        self.assertIn("<IdCodice>556000000001</IdCodice>", xml)
        self.assertIn("<Natura>N3.2</Natura>", xml)
        self.assertNotIn("EsigibilitaIVA", xml)

    def test_controlli_segnalano_dati_mancanti(self):
        self.cliente.partita_iva = self.cliente.codice_sdi = ""
        self.cliente.save()
        self.pack.prezzo_unitario = None
        self.pack.save()
        avvisi = " ".join(documenti.controlli_prefattura(documenti.genera_prefattura(self.ordine)))
        for atteso in ("partita IVA", "SDI", "prezzo a zero"):
            self.assertIn(atteso, avvisi)


class RuoliTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("dati_demo", verbosity=0)

    def accedi(self, username):
        self.client.force_login(get_user_model().objects.get(username=username))

    def test_gruppi_creati_con_i_permessi_iniziali(self):
        U = get_user_model()
        self.assertEqual(
            {g for u in U.objects.exclude(username="admin") for g in u.groups.values_list("name", flat=True)},
            {COMMERCIALE, CUSTOMER, AMMINISTRAZIONE},
        )
        self.assertTrue(U.objects.get(username="amministrazione").has_perm("ws.add_prefattura"))
        self.assertFalse(U.objects.get(username="commerciale").has_perm("ws.add_prefattura"))
        self.assertFalse(U.objects.get(username="amministrazione").has_perm("ws.change_progetto"))

    def test_commerciale_non_crea_prefatture_ma_le_consulta(self):
        self.accedi("commerciale")
        ordine = OrdineCliente.objects.get(stato="consegnato")
        r = self.client.post(reverse("ordine_genera_prefattura", args=[ordine.pk]), follow=True)
        self.assertContains(r, "Il tuo ruolo non permette")
        self.assertEqual(PreFattura.objects.count(), 1)
        pf = PreFattura.objects.get()
        self.assertEqual(self.client.get(pf.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse("prefattura_esporta", args=[pf.pk, "xml"])).status_code, 302)
        self.assertEqual(self.client.get(reverse("modifica", args=["prefattura", pf.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse("nuovo", args=["quotazione"])).status_code, 200)

    def test_amministrazione_esporta_ma_non_avanza_i_progetti(self):
        self.accedi("amministrazione")
        pf = PreFattura.objects.get()
        PreFattura.objects.update(stato="bozza")
        r = self.client.get(reverse("prefattura_esporta", args=[pf.pk, "xml"]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"FatturaElettronica", r.content)
        pf.refresh_from_db()
        self.assertEqual(pf.stato, "esportata")
        p = Progetto.objects.get(nome__startswith="Lacca")
        self.client.post(reverse("progetto_avanza", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.fase, "lead")

    def test_customer_service_genera_ordine_acquisto_e_ddt(self):
        self.accedi("customer")
        bozza = OrdineCliente.objects.get(stato="bozza")
        r = self.client.post(reverse("ordine_genera_acquisto", args=[bozza.pk]))
        oa = OrdineAcquisto.objects.get(ordine=bozza)
        self.assertRedirects(r, oa.get_absolute_url())
        # riordino da 8.000: bombole e cap coperti, erogatori da riacquistare (MOQ 10.000, eccedenza 7.000)
        self.assertEqual([(x.tipo, x.quantita) for x in oa.righe.all()], [("prodotto", 8000), ("packaging", 7000)])
        self.client.post(reverse("ordine_genera_ddt", args=[bozza.pk]))
        self.assertEqual(DDT.objects.filter(ordine=bozza).count(), 1)


class ListinoRiordiniPromemoriaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("dati_demo", verbosity=0)

    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username="commerciale"))

    def test_nuova_versione_della_quotazione(self):
        p = Progetto.objects.get(nome__startswith="Shampoo")
        accettata = flusso.quotazione_accettata(p)
        r = self.client.post(reverse("quotazione_duplica", args=[accettata.pk]))
        nuova = p.quotazioni.order_by("-numero").first()
        self.assertRedirects(r, reverse("modifica", args=["quotazione", nuova.pk]))
        self.assertEqual((nuova.numero, nuova.stato), (accettata.numero + 1, "bozza"))
        self.assertEqual(
            [(x.descrizione, x.quantita, x.prezzo_unitario) for x in nuova.righe.all()],
            [(x.descrizione, x.quantita, x.prezzo_unitario) for x in accettata.righe.all()],
        )
        accettata.refresh_from_db()
        self.assertEqual(accettata.stato, "accettata")  # resta valida finché la nuova non è accettata

    def test_offerta_non_mostra_i_costi(self):
        q = Quotazione.objects.get(progetto__nome__startswith="Deodorante")
        r = self.client.get(reverse("quotazione_stampa", args=[q.pk]))
        self.assertContains(r, "1,050")
        self.assertNotContains(r, "0,740")

    def test_listino_dallo_storico_e_verso_una_quotazione(self):
        from .models import RigaQuotazione, VoceListino

        riga = RigaQuotazione.objects.filter(voci_listino__isnull=True, quotazione__progetto__produttore__isnull=False).first()
        prima = VoceListino.objects.count()
        self.client.post(reverse("listino_salva_riga", args=[riga.pk]))
        voce = VoceListino.objects.get(origine=riga)
        self.assertEqual(VoceListino.objects.count(), prima + 1)
        self.assertEqual((voce.quantita_minima, voce.costo_unitario, voce.produttore), (riga.quantita, riga.costo_unitario, riga.quotazione.progetto.produttore))

        p = Progetto.objects.get(nome__startswith="Lacca")
        q = Quotazione.objects.create(progetto=p)
        r = self.client.post(reverse("listino_usa", args=[voce.pk, q.pk]))
        self.assertRedirects(r, p.get_absolute_url())
        self.assertEqual([(x.descrizione, x.prezzo_unitario) for x in q.righe.all()], [(voce.descrizione, voce.prezzo_unitario)])

    def test_voci_scadute_nascoste(self):
        from .models import VoceListino

        v = VoceListino.objects.first()
        v.valido_fino = oggi() - timedelta(days=1)
        v.save()
        self.assertNotIn(v, flusso.voci_listino())
        self.assertIn(v, flusso.voci_listino(scadute=True))

    def test_riordino_rapido(self):
        prodotto = Prodotto.objects.get(codice="LUM-MOU-200")
        r = self.client.post(reverse("prodotto_riordino", args=[prodotto.pk]))
        ordine = OrdineCliente.objects.order_by("-pk").first()
        self.assertRedirects(r, ordine.get_absolute_url())
        riga = ordine.righe.get()
        self.assertEqual((ordine.stato, ordine.produttore.nome, riga.quantita, str(riga.prezzo_unitario)), ("bozza", "Biopharma", 8000, "2.6500"))

    def test_promemoria(self):
        from .models import Promemoria

        p = Progetto.objects.get(nome__startswith="Deodorante")
        m = p.promemoria.get()
        self.assertTrue(m.scaduto)
        self.assertEqual(m.cliente, p.cliente)  # ricavato dal progetto
        self.assertContains(self.client.get(reverse("dashboard")), m.testo)
        self.client.post(reverse("promemoria_fatto", args=[m.pk]))
        m.refresh_from_db()
        self.assertTrue(m.fatto)
        self.assertTrue(p.eventi.filter(testo__startswith="Fatto:").exists())
        self.assertNotIn(m, self.client.get(reverse("dashboard")).context["promemoria"])
        self.assertEqual(Promemoria.objects.filter(fatto=False).count(), 3)

    def test_ricerca(self):
        r = self.client.get(reverse("cerca") + "?q=lumi")
        self.assertContains(r, "Lumière Beauty Srl")
        r = self.client.get(reverse("cerca") + "?q=LUM-MOU")
        self.assertContains(r, "Mousse volumizzante Lumière")


class ImpiantiScadenzePdfTest(DocumentiTest):
    def test_impianti_solo_al_primo_ordine_con_artwork_nuovo(self):
        artwork = self.pack.artwork
        artwork.costo_impianto, artwork.prezzo_impianto = "650", "800"
        artwork.save()
        oa = documenti.genera_ordine_acquisto(self.ordine)
        pf = documenti.genera_prefattura(self.ordine)
        self.assertEqual([(r.tipo, str(r.costo_unitario)) for r in oa.righe.all()][-1], ("impianti", "650.0000"))
        self.assertEqual([(r.tipo, str(r.prezzo_unitario)) for r in pf.righe.all()][-1], ("impianti", "800.0000"))
        flusso.registra_packaging(self.ordine)
        riordino = OrdineCliente.objects.create(cliente=self.cliente, produttore=self.produttore)
        RigaOrdine.objects.create(ordine=riordino, prodotto=self.prodotto, quantita=8000, prezzo_unitario="2.65")
        self.assertEqual([r.tipo for r in documenti.genera_ordine_acquisto(riordino).righe.all()], ["prodotto"])
        self.assertEqual([r.tipo for r in documenti.genera_prefattura(riordino).righe.all()], ["prodotto"])

    def test_fattura_del_produttore_diversa_dall_ordine(self):
        oa = documenti.genera_ordine_acquisto(self.ordine)
        oa.importo_fattura_fornitore = oa.totale
        oa.save()
        self.assertIsNone(oa.differenza_fattura)
        self.assertEqual(flusso.fatture_produttore_diverse(), [])
        oa.importo_fattura_fornitore = oa.totale + 180
        oa.save()
        self.assertEqual(oa.differenza_fattura, 180)
        self.assertEqual(flusso.fatture_produttore_diverse(), [oa])

    def test_pagamenti_da_verificare(self):
        pf = documenti.genera_prefattura(self.ordine)
        self.assertNotIn(pf, flusso.pagamenti_da_verificare())  # senza scadenza
        pf.data_scadenza = oggi() + timedelta(days=30)
        pf.save()
        self.assertNotIn(pf, flusso.pagamenti_da_verificare())
        pf.data_scadenza = oggi() + timedelta(days=5)
        pf.save()
        self.assertIn(pf, flusso.pagamenti_da_verificare())
        pf.pagata = True
        pf.save()
        self.assertNotIn(pf, flusso.pagamenti_da_verificare())

    def test_riordini_da_sollecitare(self):
        self.ordine.stato = "consegnato"
        self.ordine.save()
        self.prodotto.prossima_consegna = oggi() + timedelta(days=300)
        self.prodotto.save()
        self.assertEqual(flusso.riordini_da_sollecitare(), [])  # mancano più di 30 giorni al limite per ordinare
        self.prodotto.prossima_consegna = oggi() + timedelta(days=160)
        self.prodotto.save()
        (r,) = flusso.riordini_da_sollecitare()
        self.assertEqual((r["prodotto"], r["mancano"]), (self.prodotto, 10))
        riordino = OrdineCliente.objects.create(cliente=self.cliente, produttore=self.produttore)
        RigaOrdine.objects.create(ordine=riordino, prodotto=self.prodotto, quantita=1000)
        self.assertEqual(flusso.riordini_da_sollecitare(), [])  # c'è già un ordine aperto

    def test_pdf_su_carta_intestata(self):
        U = get_user_model()
        self.client.force_login(U.objects.create_user("x", password="x"))
        q = Quotazione.objects.get(progetto=self.progetto)
        documenti.genera_ddt(self.ordine)
        casi = [("offerta", q), ("conferma", self.ordine), ("ddt", self.ordine.ddt.get()), ("prefattura", documenti.genera_prefattura(self.ordine)), ("acquisto", documenti.genera_ordine_acquisto(self.ordine))]
        for tipo, obj in casi:
            with self.subTest(tipo=tipo):
                r = self.client.get(reverse("pdf", args=[tipo, obj.pk]))
                self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
                self.assertTrue(r.content.startswith(b"%PDF"))
                self.assertIn(".pdf", r["Content-Disposition"])


class BriefTest(TestCase):
    def setUp(self):
        self.modello = modulo_brief.modello_dimostrativo()
        self.campi = modulo_brief.analizza(self.modello)
        self.per_etichetta = {c.etichetta: c for c in self.campi}

    def test_riconosce_campi_ed_etichette(self):
        self.assertEqual(
            [(c.tipo, c.etichetta) for c in self.campi[:9]],
            [("menu", "KAM"), ("data", "DATE"), ("testo", "CUSTOMER"), ("testo", "DESCRIPTION"), ("testo", "PROJECT NAME"),
             ("data", "LAUNCH DATE"), ("cella", "TARGET PRICE*"), ("testo", "MARKET"), ("testo", "MOQ")],
        )  # fmt: skip
        self.assertEqual(self.per_etichetta["KAM"].opzioni, ["ROSSI", "BIANCHI"])
        self.assertEqual(self.per_etichetta["DESCRIPTION"].sezione, "IF NEW")
        self.assertEqual((self.per_etichetta["LABEL"].tipo, self.per_etichetta["LABEL"].gruppo), ("casella", "SECONDARY PACK"))
        self.assertIn("PATCH TEST · BF/Customer", self.per_etichetta)  # riga di dettaglio abbinata alla casella
        self.assertTrue(all(not c.valore for c in self.campi))  # i segnaposto non sono valori

    def test_compila_solo_i_campi_indicati(self):
        e = self.per_etichetta
        valori = {
            e["KAM"].chiave: "BIANCHI", e["PROJECT NAME"].chiave: "Mousse è & <prova>\nseconda riga",
            e["TARGET PRICE*"].chiave: "1,60 EUR", e["LABEL"].chiave: True, e["PATCH TEST · BF/Customer"].chiave: "CLIENTE",
        }  # fmt: skip
        compilato = modulo_brief.compila(self.modello, valori)
        import io, zipfile

        xml = zipfile.ZipFile(io.BytesIO(compilato)).read("word/document.xml").decode()
        for atteso in ("BIANCHI", "Mousse è &amp; &lt;prova&gt;", "seconda riga", "1,60 EUR", "CLIENTE", "☒"):
            self.assertIn(atteso, xml)
        self.assertEqual(xml.count("☒"), 1)
        self.assertEqual(xml.count('w14:val="1"'), 1)
        # i campi non compilati restano segnaposto, come nel modulo vuoto
        self.assertEqual(xml.count("<w:showingPlcHdr/>"), self.modello_segnaposto() - 3)
        riletti = {c.etichetta: c.valore for c in modulo_brief.analizza(compilato)}
        self.assertEqual((riletti["KAM"], riletti["LABEL"], riletti["LEAFLET"], riletti["MARKET"]), ("BIANCHI", True, False, ""))

    def modello_segnaposto(self):
        import io, zipfile

        return zipfile.ZipFile(io.BytesIO(self.modello)).read("word/document.xml").decode().count("<w:showingPlcHdr/>")

    def test_file_non_valido(self):
        with self.assertRaises(modulo_brief.BriefError):
            modulo_brief.analizza(b"non sono un docx")


class BriefPagineTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("dati_demo", verbosity=0)

    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username="commerciale"))

    def test_nuovo_brief_precompilato_salvato_e_scaricato(self):
        from .models import Brief

        p = Progetto.objects.get(nome__startswith="Shampoo")
        r = self.client.post(reverse("brief_nuovo", args=[p.pk]))
        b = Brief.objects.get(progetto=p)
        self.assertRedirects(r, b.get_absolute_url())
        campi = {c.etichetta: c.chiave for c in modulo_brief.analizza(b.modello.read())}
        self.assertEqual(b.valori[campi["PROJECT NAME"]], p.nome)
        self.assertEqual(b.valori[campi["MOQ"]], "12000")
        self.assertEqual(b.valori[campi["TARGET PRICE*"]], "1,60 EUR")
        self.assertIn(campi["DATE"], b.valori)
        self.assertNotIn(campi["LAUNCH DATE"], [k for k, v in b.valori.items() if v == b.valori[campi["DATE"]] and k != campi["DATE"]])

        dati = {campi["PROJECT NAME"]: "Shampoo senza SLES", campi["LABEL"]: "1", campi["KAM"]: "valore non previsto", "stato": "inviato", "note": "x", "azione": "scarica"}
        r = self.client.post(b.get_absolute_url(), dati)
        self.assertRedirects(r, reverse("brief_scarica", args=[b.pk]), fetch_redirect_response=False)
        b.refresh_from_db()
        self.assertEqual(b.valori, {campi["PROJECT NAME"]: "Shampoo senza SLES", campi["LABEL"]: True})  # il menu accetta solo le sue opzioni
        self.assertEqual((b.stato, b.data_invio), ("inviato", oggi()))
        r = self.client.get(reverse("brief_scarica", args=[b.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Technical Brief Shampoo delicato 250 ml.docx", r["Content-Disposition"])
        riletti = {c.etichetta: c.valore for c in modulo_brief.analizza(r.content)}
        self.assertEqual((riletti["PROJECT NAME"], riletti["LABEL"], riletti["CUSTOMER"]), ("Shampoo senza SLES", True, ""))

    def test_senza_modello_avvisa(self):
        p = Progetto.objects.get(nome__startswith="Deodorante")  # produttore senza modulo caricato
        r = self.client.post(reverse("brief_nuovo", args=[p.pk]), follow=True)
        self.assertContains(r, "Carica prima il modello del brief")

    def test_amministrazione_non_modifica_il_brief(self):
        from .models import Brief

        b = Brief.objects.first()
        self.client.force_login(get_user_model().objects.get(username="amministrazione"))
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 200)
        prima = dict(b.valori)
        self.client.post(b.get_absolute_url(), {"stato": "bozza"})
        b.refresh_from_db()
        self.assertEqual(b.valori, prima)


class SpedizioneTest(DocumentiTest):
    def setUp(self):
        super().setUp()
        p = self.prodotto
        p.nome, p.formato, p.hs_code, p.pezzi_per_cartone = "Mousse", "150 mL", "33049900", 12
        p.un_numero, p.un_denominazione, p.un_classe, p.un_ems, p.quantita_limitata = "UN 1950", "AEROSOL", "2.1", "F-D, S-U", True
        p.imballo_interno = "metal inners x 150 mL net each"
        p.save()
        self.ordine.righe.update(lotto="260743")

    def test_note_e_lotto_su_ddt_e_prefattura(self):
        ddt = documenti.genera_ddt(self.ordine)
        self.assertEqual(ddt.righe.get().lotto, "260743")
        self.assertIn("HS CODE 33049900", ddt.note)
        self.assertIn("DANGEROUS GOODS UN1950 SHIPPED UNDER ADR EXEMPTION FOR LIMITED QUANTITIES", ddt.note)
        self.assertEqual(documenti.genera_prefattura(self.ordine).note, ddt.note)
        self.prodotto.quantita_limitata = False
        self.prodotto.save()
        self.assertEqual(documenti.note_spedizione(self.ordine), "HS CODE 33049900")

    def test_spedizione_dall_ordine_e_dichiarazione(self):
        sp = documenti.genera_spedizione(self.ordine)
        collo = sp.colli.get()
        self.assertEqual((collo.descrizione, collo.un, collo.cartoni, collo.lotto, collo.numero), ("Mousse 150 mL", "UN1950", 417, "260743", 1))
        collo.peso_lordo_kg, collo.peso_netto_kg = "500", "470"
        collo.save()
        sp.colli.create(prodotto=self.prodotto, quantita=100, cartoni=9, peso_lordo_kg="20.5", peso_netto_kg="18")
        sp.colli.create(descrizione="Packaging material", peso_lordo_kg="150", peso_netto_kg="130")
        sp.colli.create(descrizione="Bulk", un="UN3082", descrizione_adr="UN 3082, ENVIRONMENTALLY HAZARDOUS SUBSTANCE, LIQUID, N.O.S., 9, III", peso_lordo_kg="311", peso_netto_kg="302")
        self.assertEqual([c.numero for c in sp.colli.all()], [1, 2, 3, 4])
        tot = sp.totali
        self.assertEqual((tot["pallet"], str(tot["lordo"]), str(tot["netto"]), tot["cartoni"]), (4, "981.50", "920.00", 426))
        aerosol, bulk = sp.merci_pericolose()  # il materiale non pericoloso resta fuori dalla dichiarazione
        self.assertEqual((aerosol["prodotto"], aerosol["cartoni"], str(aerosol["lordo"]), aerosol["pallet"]), (self.prodotto, 426, "520.50", 2))
        self.assertEqual((bulk["prodotto"], str(bulk["netto"])), (None, "302.00"))

        self.client.force_login(get_user_model().objects.create_user("y", password="y"))
        r = self.client.get(sp.get_absolute_url())
        self.assertContains(r, "contatto d&#x27;emergenza 24h")  # dati mancanti segnalati
        for tipo in ("packing", "multimodale"):
            r = self.client.get(reverse("pdf", args=[tipo, sp.pk]))
            self.assertTrue(r.content.startswith(b"%PDF"))

    def test_contenuto_della_dichiarazione(self):
        from django.template.loader import render_to_string

        sp = documenti.genera_spedizione(self.ordine)
        sp.colli.update(peso_lordo_kg="994", peso_netto_kg="925")
        html = render_to_string("ws/multimodale.html", {"sp": sp, "azienda": Azienda.corrente(), "pericolose": sp.merci_pericolose()})
        for atteso in ("UN 1950, AEROSOL, 2.1", "EmS: F-D, S-U", "Limited Quantity", "417 fibreboard boxes each containing", "12 metal inners x 150 mL net each", "994,00", "MULTIMODAL DANGEROUS GOODS FORM"):
            self.assertIn(atteso, html)

    def test_documenti_in_inglese_per_il_cliente_estero(self):
        from django.test import RequestFactory

        from .views import _html_pdf

        ddt = documenti.genera_ddt(self.ordine)
        italiano = _html_pdf(RequestFactory().get("/"), "ws/ddt.html", "d", ddt, Azienda.corrente(), None)
        self.assertIn("Documento di trasporto", italiano)
        self.cliente.lingua_documenti = "en"
        self.cliente.save()
        ddt.refresh_from_db()
        inglese = _html_pdf(RequestFactory().get("/"), "ws/ddt.html", "d", ddt, Azienda.corrente(), None)
        for atteso in ("Transport document", "Messrs.", "Gross weight", "Signature of addressee", "5.000"):
            self.assertIn(atteso, inglese)
        self.assertNotIn("Documento di trasporto", inglese)
        self.client.force_login(get_user_model().objects.create_user("z", password="z"))
        pf = documenti.genera_prefattura(self.ordine)
        self.assertTrue(self.client.get(reverse("pdf", args=["prefattura", pf.pk])).content.startswith(b"%PDF"))

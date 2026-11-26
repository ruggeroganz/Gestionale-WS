from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

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
        self.assertEqual(test.versione_formula, self.v1)
        self.assertEqual(test.data_fine_prevista, oggi() + timedelta(days=90))

        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)  # il packaging non parte senza stabilità superata
        test.esito = "superata"
        test.save()
        flusso.avanza(p)
        self.assertEqual(p.fase, "packaging")

        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)
        prodotto, _, _ = self.prodotto_con_bombola()
        flusso.avanza(p)
        self.assertEqual(p.fase, "ordine")
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.stato, "attivo")

        ordine = OrdineCliente.objects.create(cliente=self.cliente, progetto=p, produttore=self.produttore, stato="accettata")
        RigaOrdine.objects.create(ordine=ordine, prodotto=prodotto, quantita=5000)
        flusso.avanza(p)
        with self.assertRaises(flusso.FlussoError):
            flusso.avanza(p)
        ordine.stato = "consegnato"
        ordine.save()
        flusso.avanza(p)
        self.assertEqual((p.fase, p.stato), ("consegnato", "chiuso"))

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
        p.produttore = self.produttore
        p.data_consegna_richiesta = oggi() + timedelta(days=100)  # meno di 150 + 90 giorni
        p.save()
        tappe = flusso.planner(p)
        self.assertEqual(tappe[-1]["data"], p.data_consegna_richiesta)
        self.assertEqual(tappe[1]["data"], p.data_consegna_richiesta - timedelta(days=240))
        self.assertTrue(flusso.in_ritardo(p))


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
        urls = [reverse(n) for n in ("dashboard", "progetti", "clienti", "produttori", "formule", "prodotti", "catalogo", "magazzino", "listino", "ordini", "acquisti", "ddt_elenco", "prefatture")]
        urls.append(reverse("listino") + "?q=mousse")
        urls.append(reverse("progetti") + "?stato=tutti")
        urls += [p.get_absolute_url() for p in Progetto.objects.all()]
        urls += [c.get_absolute_url() for c in Cliente.objects.all()]
        urls += [p.get_absolute_url() for p in Prodotto.objects.all()]
        for o in OrdineCliente.objects.all():
            urls += [o.get_absolute_url(), reverse("ordine_stampa", args=[o.pk])]
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
        r = self.client.post(url, {"progetto": p.pk, "data": q.data.isoformat(), "stato": "accettata", "next": p.get_absolute_url()})
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

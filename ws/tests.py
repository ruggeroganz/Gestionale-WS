from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import flusso
from .models import (
    Artwork,
    Campionatura,
    Cliente,
    Componente,
    Formula,
    MovimentoPackaging,
    OrdineCliente,
    Packaging,
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
        self.client.force_login(get_user_model().objects.get(username="customer"))

    def test_login_obbligatorio(self):
        self.client.logout()
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, "/accedi/?next=/")

    def test_tutte_le_pagine_si_aprono(self):
        urls = [reverse(n) for n in ("dashboard", "progetti", "clienti", "produttori", "formule", "prodotti", "catalogo", "magazzino", "listino", "ordini")]
        urls.append(reverse("listino") + "?q=mousse")
        urls.append(reverse("progetti") + "?stato=tutti")
        urls += [p.get_absolute_url() for p in Progetto.objects.all()]
        urls += [c.get_absolute_url() for c in Cliente.objects.all()]
        urls += [p.get_absolute_url() for p in Prodotto.objects.all()]
        for o in OrdineCliente.objects.all():
            urls += [o.get_absolute_url(), reverse("ordine_stampa", args=[o.pk])]
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

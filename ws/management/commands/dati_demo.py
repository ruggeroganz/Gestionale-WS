"""Carica utenti, ruoli e dati di esempio (inventati) per provare il gestionale."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from ws import documenti, flusso
from ws.models import (
    Artwork,
    Azienda,
    Campionatura,
    Cliente,
    Componente,
    Contatto,
    Evento,
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
    RigaQuotazione,
    TestStabilita,
    VersioneFormula,
    oggi,
)

PASSWORD = "demo1234"


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **opts):
        if Progetto.objects.exists():
            raise CommandError("Il database contiene già dei progetti: dati demo non caricati.")
        User = get_user_model()
        t = oggi()

        def giorni(n):
            return t + timedelta(days=n)

        utenti = {}
        for username, nome, cognome, gruppo in [
            ("commerciale", "Giulia", "Commerciale", "Commerciale"),
            ("customer", "Marco", "Customer Service", "Customer service e acquisti"),
            ("amministrazione", "Elena", "Amministrazione", "Amministrazione"),
        ]:
            g, _ = Group.objects.get_or_create(name=gruppo)
            u = User.objects.create_user(username, password=PASSWORD, first_name=nome, last_name=cognome)
            u.groups.add(g)
            utenti[username] = u
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", password=PASSWORD)

        Azienda.objects.create(ragione_sociale="WS Srl (demo)", partita_iva="00000000000", indirizzo="Via Demo 1", cap="20100", comune="Milano", provincia="MI", iban="IT00X0000000000000000000000")
        bio = Produttore.objects.create(nome="Biopharma", paese="Italia", indirizzo="Zona industriale (indirizzo demo)", lead_time_giorni=150, note="Full service, produzione italiana.")
        cina = Produttore.objects.create(nome="Guangzhou Beauty Manufacturing", paese="Cina", lead_time_giorni=180, note="Full service, include trasporto via mare.")

        lum = Cliente.objects.create(ragione_sociale="Lumière Beauty Srl", tipo="brand", stato="attivo", paese="Italia", indirizzo="Via Esempio 12", cap="20121", comune="Milano", provincia="MI", codice_sdi="ABC1234", pagamento="Bonifico 30 gg d.f.f.m.", partita_iva="00000000001", commerciale=utenti["commerciale"])
        aur = Cliente.objects.create(ragione_sociale="Profumerie Aurora SpA", tipo="catena", stato="attivo", paese="Italia", indirizzo="Corso Demo 5", cap="40121", comune="Bologna", provincia="BO", pec="aurora@example.com", pagamento="Bonifico 60 gg d.f.f.m.", partita_iva="00000000002", commerciale=utenti["commerciale"])
        nor = Cliente.objects.create(ragione_sociale="Nordic Glow AB", tipo="brand", stato="potenziale", paese="Svezia", codice_paese="SE", commerciale=utenti["commerciale"])
        Contatto.objects.create(cliente=lum, nome="Sara Bianchi", ruolo="Product manager", email="sara@example.com")
        Contatto.objects.create(cliente=aur, nome="Luca Verdi", ruolo="Buyer private label", email="luca@example.com")

        bombola = Componente.objects.create(codice="BOM-AL-200", tipo="bombola", descrizione="Bombola alluminio 200 ml", materiale="Alluminio", formato="200 ml, Ø 45 mm")
        cap = Componente.objects.create(codice="CAP-45", tipo="tappo", descrizione="Cap per bombola Ø 45", materiale="PP", formato="Ø 45 mm")
        erog = Componente.objects.create(codice="ERO-MOU", tipo="erogatore", descrizione="Erogatore mousse verticale", materiale="PP")
        Componente.objects.create(codice="FLA-PET-250", tipo="flacone", descrizione="Flacone PET 250 ml", materiale="PET", formato="250 ml")
        Componente.objects.create(codice="FOAM-43", tipo="foamer", descrizione="Foamer 43 mm", materiale="PP", formato="Ø 43 mm")

        # --- Progetto 1: prodotto già consegnato, con residuo di packaging e formula aggiornata
        p1 = Progetto.objects.create(nome="Mousse volumizzante 200 ml", cliente=lum, produttore=bio, tipo_prodotto="Mousse capelli", fase="consegnato", stato="chiuso", responsabile=utenti["customer"], quantita_prevista=5000, prezzo_target=D("2.90"), data_consegna_richiesta=giorni(-30), brief="Mousse volumizzante, profumazione fiorita, bombola litografata bianca.")
        f1 = Formula.objects.create(codice="BIO-MOU-014", nome="Mousse volumizzante", produttore=bio, progetto=p1, categoria="Capelli")
        f1v1 = VersioneFormula.objects.create(formula=f1, data=giorni(-330), inci="Aqua, Butane, Propane, VP/VA Copolymer, Polyquaternium-11, Parfum, Phenoxyethanol, Citric Acid")
        f1v2 = VersioneFormula.objects.create(formula=f1, data=giorni(-10), inci="Aqua, Butane, Propane, VP/VA Copolymer, Polyquaternium-11, Panthenol, Parfum, Phenoxyethanol, Citric Acid", modifiche="Aggiunto pantenolo per migliorare la tenuta.")
        q1 = Quotazione.objects.create(progetto=p1, versione_formula=f1v1, data=giorni(-340), stato="accettata")
        RigaQuotazione.objects.create(quotazione=q1, tipo="prodotto", descrizione="Mousse 200 ml, bombola litografata, full service", quantita=5000, costo_unitario=D("1.850"), prezzo_unitario=D("2.750"))
        RigaQuotazione.objects.create(quotazione=q1, tipo="packaging", descrizione="Bombola alluminio 200 ml litografata, eccedenza MOQ", quantita=15000, costo_unitario=D("0.420"), prezzo_unitario=D("0.480"))
        RigaQuotazione.objects.create(quotazione=q1, tipo="packaging", descrizione="Cap Ø 45 pantone, eccedenza MOQ", quantita=25000, costo_unitario=D("0.060"), prezzo_unitario=D("0.072"))
        RigaQuotazione.objects.create(quotazione=q1, tipo="una_tantum", descrizione="Impianti litografia", quantita=1, costo_unitario=D("650"), prezzo_unitario=D("800"))
        Campionatura.objects.create(progetto=p1, versione_formula=f1v1, data_invio=giorni(-320), esito="approvata", data_feedback=giorni(-305), feedback="Texture e profumo approvati.")
        TestStabilita.objects.create(progetto=p1, versione_formula=f1v1, data_inizio=giorni(-300), esito="superata", data_esito=giorni(-210), note="Compatibile con la bombola.")
        a1 = Artwork.objects.create(cliente=lum, progetto=p1, nome="Litografia bombola 200 ml", versione_formula=f1v1, stato="approvato", data_approvazione=giorni(-200))
        k_bom = Packaging.objects.create(cliente=lum, componente=bombola, descrizione="Bombola 200 ml litografata Lumière", decorazione="litografia", colore="Bianco + Pantone 7421 C", artwork=a1, riporta_inci=True, moq=20000, costo_unitario=D("0.420"), prezzo_unitario=D("0.480"))
        k_cap = Packaging.objects.create(cliente=lum, componente=cap, descrizione="Cap Ø 45 Pantone 7421 C", decorazione="colore", colore="Pantone 7421 C", moq=30000, costo_unitario=D("0.060"), prezzo_unitario=D("0.072"))
        k_ero = Packaging.objects.create(cliente=lum, componente=erog, descrizione="Erogatore mousse bianco", decorazione="neutro", moq=10000, costo_unitario=D("0.110"), prezzo_unitario=D("0.130"))
        sku1 = Prodotto.objects.create(codice="LUM-MOU-200", nome="Mousse volumizzante Lumière", cliente=lum, progetto=p1, versione_formula=f1v2, formato="200 ml")
        for k in (k_bom, k_cap, k_ero):
            RigaDistinta.objects.create(prodotto=sku1, packaging=k)
        o1 = OrdineCliente.objects.create(cliente=lum, progetto=p1, produttore=bio, data=giorni(-195), data_consegna_prevista=giorni(-40), stato="consegnato", riferimento_cliente="PO-2291")
        RigaOrdine.objects.create(ordine=o1, prodotto=sku1, quantita=5000, prezzo_unitario=D("2.750"))
        flusso.registra_packaging(o1)
        MovimentoPackaging.objects.filter(ordine=o1).update(data=giorni(-45))
        oa = documenti.genera_ordine_acquisto(o1)
        oa.data, oa.stato, oa.ddt_fornitore, oa.fattura_fornitore, oa.importo_fattura_fornitore = giorni(-194), "ricevuto", f"n. 812 del {giorni(-42):%d/%m/%Y}", f"n. 1045 del {giorni(-40):%d/%m/%Y}", oa.totale
        oa.save()
        ddt = documenti.genera_ddt(o1)
        ddt.data, ddt.vettore, ddt.colli, ddt.aspetto = giorni(-41), "Corriere demo", 14, "Cartoni su pallet"
        ddt.save()
        pf = documenti.genera_prefattura(o1)
        pf.data, pf.data_scadenza = giorni(-40), giorni(20)
        pf.save()
        Evento.objects.create(progetto=p1, testo="Prima produzione consegnata: 5.000 pezzi. Residuo di packaging in deposito da Biopharma.", automatico=True)
        Evento.objects.create(progetto=p1, utente=utenti["customer"], testo="Biopharma propone la formula v2 con pantenolo per il riordino. Da verificare le bombole già litografate.")
        o2 = OrdineCliente.objects.create(cliente=lum, progetto=p1, produttore=bio, data=t, data_consegna_prevista=giorni(60), stato="bozza", note="Riordino.")
        RigaOrdine.objects.create(ordine=o2, prodotto=sku1, quantita=8000, prezzo_unitario=D("2.650"))

        # --- Progetto 2: in stabilità
        p2 = Progetto.objects.create(nome="Shampoo delicato 250 ml", cliente=aur, produttore=bio, tipo_prodotto="Shampoo", fase="stabilita", responsabile=utenti["customer"], quantita_prevista=12000, prezzo_target=D("1.60"), data_consegna_richiesta=giorni(200), brief="Linea a marchio della catena, flacone PET con etichetta.")
        f2 = Formula.objects.create(codice="BIO-SHA-031", nome="Shampoo delicato", produttore=bio, progetto=p2, categoria="Capelli")
        f2v1 = VersioneFormula.objects.create(formula=f2, data=giorni(-110), inci="Aqua, Sodium Laureth Sulfate, Cocamidopropyl Betaine, Glycerin, Parfum, Sodium Benzoate, Citric Acid")
        f2v2 = VersioneFormula.objects.create(formula=f2, data=giorni(-80), inci="Aqua, Sodium Coco-Sulfate, Cocamidopropyl Betaine, Glycerin, Parfum, Sodium Benzoate, Citric Acid", modifiche="Sostituito SLES su richiesta del cliente.")
        q2 = Quotazione.objects.create(progetto=p2, versione_formula=f2v1, data=giorni(-115), stato="superata")
        RigaQuotazione.objects.create(quotazione=q2, descrizione="Shampoo 250 ml, flacone PET con etichetta, full service", quantita=12000, costo_unitario=D("0.980"), prezzo_unitario=D("1.450"))
        q2b = Quotazione.objects.create(progetto=p2, versione_formula=f2v2, data=giorni(-78), stato="accettata", motivo="Tensioattivo senza SLES, costo materia prima più alto.")
        RigaQuotazione.objects.create(quotazione=q2b, descrizione="Shampoo 250 ml senza SLES, flacone PET con etichetta, full service", quantita=12000, costo_unitario=D("1.060"), prezzo_unitario=D("1.560"))
        Campionatura.objects.create(progetto=p2, versione_formula=f2v1, data_invio=giorni(-105), esito="modifiche", data_feedback=giorni(-90), feedback="Chiedono una versione senza SLES.")
        Campionatura.objects.create(progetto=p2, versione_formula=f2v2, data_invio=giorni(-75), esito="approvata", data_feedback=giorni(-62))
        TestStabilita.objects.create(progetto=p2, versione_formula=f2v2, data_inizio=giorni(-60))
        Artwork.objects.create(cliente=aur, progetto=p2, nome="Etichetta fronte/retro 250 ml", versione_formula=f2v2, stato="bozza")

        # --- Progetto 3: quotazione inviata a un potenziale cliente
        p3 = Progetto.objects.create(nome="Deodorante spray 150 ml", cliente=nor, produttore=cina, tipo_prodotto="Deodorante spray", fase="quotazione", responsabile=utenti["commerciale"], quantita_prevista=30000, prezzo_target=D("1.10"), data_consegna_richiesta=giorni(330))
        q3 = Quotazione.objects.create(progetto=p3, data=giorni(-6), valida_fino=giorni(24), stato="inviata")
        RigaQuotazione.objects.create(quotazione=q3, descrizione="Deodorante spray 150 ml, bombola litografata, full service", quantita=30000, costo_unitario=D("0.740"), prezzo_unitario=D("1.050"))
        RigaQuotazione.objects.create(quotazione=q3, descrizione="Deodorante spray 150 ml, bombola litografata, full service", quantita=50000, costo_unitario=D("0.690"), prezzo_unitario=D("0.980"))

        # --- Progetto 4: campionature in corso
        p4 = Progetto.objects.create(nome="Mousse detergente viso 150 ml", cliente=lum, produttore=bio, tipo_prodotto="Detergente viso foamer", fase="campionatura", responsabile=utenti["customer"], quantita_prevista=6000, data_consegna_richiesta=giorni(290))
        f4 = Formula.objects.create(codice="BIO-DET-007", nome="Mousse detergente viso", produttore=bio, progetto=p4, categoria="Viso")
        f4v1 = VersioneFormula.objects.create(formula=f4, data=giorni(-40), inci="Aqua, Coco-Glucoside, Glycerin, Disodium Cocoyl Glutamate, Parfum, Sodium Benzoate")
        f4v2 = VersioneFormula.objects.create(formula=f4, data=giorni(-12), inci="Aqua, Coco-Glucoside, Glycerin, Disodium Cocoyl Glutamate, Niacinamide, Sodium Benzoate", modifiche="Tolto il profumo, aggiunta niacinamide.")
        q4 = Quotazione.objects.create(progetto=p4, versione_formula=f4v1, data=giorni(-45), stato="accettata")
        RigaQuotazione.objects.create(quotazione=q4, descrizione="Mousse detergente 150 ml, flacone con foamer, full service", quantita=6000, costo_unitario=D("1.320"), prezzo_unitario=D("1.950"))
        Campionatura.objects.create(progetto=p4, versione_formula=f4v1, data_invio=giorni(-35), esito="modifiche", data_feedback=giorni(-20), feedback="Senza profumo e con niacinamide.")
        Campionatura.objects.create(progetto=p4, versione_formula=f4v2, data_invio=giorni(-8))

        # --- Progetto 5: lead con data di consegna troppo vicina
        Progetto.objects.create(nome="Lacca forte 300 ml", cliente=aur, tipo_prodotto="Lacca capelli", fase="lead", responsabile=utenti["commerciale"], quantita_prevista=10000, data_consegna_richiesta=giorni(170), brief="Richiesta ricevuta in fiera, da assegnare a un produttore.")

        self.stdout.write(self.style.SUCCESS(f"Dati demo caricati. Utenti: commerciale, customer, amministrazione, admin (password: {PASSWORD})."))

"""Modello dati del gestionale.

Il perno è il Progetto (dal brief alla consegna). La catena
Formula -> VersioneFormula (INCI) -> Artwork -> Packaging -> giacenza
permette di sapere con quale INCI è stato stampato ogni pezzo a magazzino.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Max, Sum
from django.urls import reverse
from django.utils import timezone


def _prossimo_codice(model, prefisso, campo="codice"):
    base = f"{prefisso}-{timezone.localdate().year}-"
    numeri = [
        int(c.rsplit("-", 1)[1])
        for c in model.objects.filter(**{f"{campo}__startswith": base}).values_list(campo, flat=True)
        if c.rsplit("-", 1)[1].isdigit()
    ]
    return f"{base}{max(numeri or [0]) + 1:03d}"


def _prossimo_numero(qs, campo="numero"):
    return (qs.aggregate(m=Max(campo))["m"] or 0) + 1


def oggi():
    return timezone.localdate()


# --------------------------------------------------------------------------
# Anagrafiche
# --------------------------------------------------------------------------
class Cliente(models.Model):
    class Tipo(models.TextChoices):
        BRAND = "brand", "Brand"
        CATENA = "catena", "Catena"
        ALTRO = "altro", "Altro"

    class Stato(models.TextChoices):
        POTENZIALE = "potenziale", "Potenziale"
        ATTIVO = "attivo", "Attivo"
        INATTIVO = "inattivo", "Inattivo"

    ragione_sociale = models.CharField(max_length=200)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.BRAND)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.POTENZIALE)
    partita_iva = models.CharField("partita IVA", max_length=30, blank=True)
    paese = models.CharField(max_length=60, default="Italia")
    indirizzo = models.CharField(max_length=250, blank=True, help_text="Via e numero civico.")
    cap = models.CharField("CAP", max_length=10, blank=True)
    comune = models.CharField(max_length=80, blank=True)
    provincia = models.CharField(max_length=2, blank=True, help_text="Sigla, solo per l'Italia.")
    codice_paese = models.CharField("codice paese", max_length=2, default="IT", help_text="Sigla ISO: IT, DE, SE…")
    codice_fiscale = models.CharField(max_length=30, blank=True)
    codice_sdi = models.CharField("codice destinatario SDI", max_length=7, blank=True)
    pec = models.EmailField("PEC", blank=True)
    pagamento = models.CharField("condizioni di pagamento", max_length=120, blank=True, help_text="Es. Bonifico 30 gg d.f.f.m.")
    lingua_documenti = models.CharField(
        "lingua dei documenti", max_length=2, choices=[("it", "Italiano"), ("en", "Inglese")], default="it"
    )
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    commerciale = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="clienti"
    )
    note = models.TextField(blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ragione_sociale"]
        verbose_name_plural = "clienti"

    def __str__(self):
        return self.ragione_sociale

    def get_absolute_url(self):
        return reverse("cliente", args=[self.pk])


class Contatto(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contatti")
    nome = models.CharField(max_length=120)
    ruolo = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "contatti"

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return self.cliente.get_absolute_url()


class Produttore(models.Model):
    """Terzista full service: sviluppa la formula, compra il packaging, produce."""

    nome = models.CharField(max_length=200)
    paese = models.CharField(max_length=60, default="Italia")
    lead_time_giorni = models.PositiveIntegerField(
        "lead time (giorni)", default=150, help_text="Giorni dall'ordine definitivo alla consegna."
    )
    indirizzo = models.CharField(max_length=250, blank=True)
    partita_iva = models.CharField("partita IVA", max_length=30, blank=True)
    modello_brief = models.FileField(
        "modello del brief (Word)",
        upload_to="modelli/",
        blank=True,
        help_text="Il modulo vuoto del produttore, in formato .docx: il gestionale lo compila con i dati del brief.",
    )
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "produttori"

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("produttori")


# --------------------------------------------------------------------------
# Progetto
# --------------------------------------------------------------------------
class Progetto(models.Model):
    class Fase(models.TextChoices):
        LEAD = "lead", "Brief"
        QUOTAZIONE = "quotazione", "Offerta"
        CAMPIONATURA = "campionatura", "Campionatura"
        STABILITA = "stabilita", "Stabilità e artwork"
        PACKAGING = "packaging", "Packaging in produzione"
        PRODUZIONE = "produzione", "Produzione"
        SPEDIZIONE = "spedizione", "Spedizione e fattura"
        CONSEGNATO = "consegnato", "Concluso"

    class Sviluppo(models.TextChoices):
        NUOVA = "nuova", "Formula nuova (campionatura e stabilità)"
        ESISTENTE_CAMPIONE = "esistente_campione", "Formula esistente, con campionatura"
        ESISTENTE = "esistente", "Formula esistente, senza campionatura né stabilità"

    class CampionePackaging(models.TextChoices):
        ATTESA = "attesa", "Non ancora ricevuto"
        AL_CLIENTE = "al_cliente", "Inviato al cliente"
        APPROVATO = "approvato", "Approvato dal cliente"
        DA_RIFARE = "da_rifare", "Da rifare"

    class Stato(models.TextChoices):
        APERTO = "aperto", "Aperto"
        SOSPESO = "sospeso", "Sospeso"
        PERSO = "perso", "Perso"
        CHIUSO = "chiuso", "Chiuso"

    codice = models.CharField(max_length=20, unique=True, blank=True)
    nome = models.CharField(max_length=200)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="progetti")
    produttore = models.ForeignKey(
        Produttore, null=True, blank=True, on_delete=models.PROTECT, related_name="progetti"
    )
    tipo_prodotto = models.CharField(
        max_length=120, blank=True, help_text="Es. mousse capelli, deodorante spray, shampoo."
    )
    fase = models.CharField(max_length=20, choices=Fase.choices, default=Fase.LEAD)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.APERTO)
    responsabile = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="progetti"
    )
    quantita_prevista = models.PositiveIntegerField("quantità prevista (pezzi)", null=True, blank=True)
    prezzo_target = models.DecimalField(
        "prezzo target (€/pezzo)", max_digits=10, decimal_places=4, null=True, blank=True
    )
    data_consegna_richiesta = models.DateField(null=True, blank=True)
    brief = models.TextField(blank=True)
    sviluppo = models.CharField("tipo di sviluppo", max_length=20, choices=Sviluppo.choices, default=Sviluppo.NUOVA)
    versione_formula = models.ForeignKey(
        "VersioneFormula",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="progetti_diretti",
        verbose_name="formula esistente da usare",
        help_text="Solo per formule esistenti senza campionatura.",
    )
    lead_time_giorni = models.PositiveIntegerField(
        "lead time del packaging (giorni)",
        default=150,
        help_text="Dall'artwork definitivo alla merce pronta: 150 per le bombole, 120 per flaconi e foamer.",
    )
    campione_packaging = models.CharField(
        "campione di stampa del packaging",
        max_length=20,
        choices=CampionePackaging.choices,
        default=CampionePackaging.ATTESA,
        help_text="Prova della litografia o etichetta che il cliente approva prima della produzione.",
    )
    creato = models.DateTimeField(auto_now_add=True)
    aggiornato = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creato"]
        verbose_name_plural = "progetti"

    def __str__(self):
        return f"{self.codice} · {self.nome}"

    def save(self, *args, **kwargs):
        if not self.codice:
            self.codice = _prossimo_codice(Progetto, "PRJ")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("progetto", args=[self.pk])


class Evento(models.Model):
    """Diario del progetto: note, cambi di fase, modifiche ai dati."""

    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="eventi")
    data = models.DateTimeField(auto_now_add=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    testo = models.TextField()
    automatico = models.BooleanField(default=False)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name_plural = "eventi"

    def __str__(self):
        return self.testo[:60]


# --------------------------------------------------------------------------
# Formule, campionature, stabilità
# --------------------------------------------------------------------------
class Formula(models.Model):
    codice = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=200)
    produttore = models.ForeignKey(
        Produttore, null=True, blank=True, on_delete=models.PROTECT, related_name="formule"
    )
    progetto = models.ForeignKey(
        Progetto,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="formule",
        help_text="Lasciare vuoto per una formula standard del produttore, riutilizzabile.",
    )
    categoria = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "formule"

    def __str__(self):
        return f"{self.codice} {self.nome}"

    def get_absolute_url(self):
        return self.progetto.get_absolute_url() if self.progetto_id else reverse("formule")


class VersioneFormula(models.Model):
    formula = models.ForeignKey(Formula, on_delete=models.CASCADE, related_name="versioni")
    numero = models.PositiveIntegerField(editable=False)
    inci = models.TextField("INCI", help_text="Elenco ingredienti separati da virgola.")
    modifiche = models.TextField("modifiche rispetto alla versione precedente", blank=True)
    data = models.DateField(default=oggi)

    class Meta:
        ordering = ["formula", "numero"]
        unique_together = [("formula", "numero")]
        verbose_name = "versione formula"
        verbose_name_plural = "versioni formula"

    def __str__(self):
        return f"{self.formula.codice} v{self.numero}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_numero(VersioneFormula.objects.filter(formula=self.formula))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return self.formula.get_absolute_url()

    @property
    def inci_normalizzato(self):
        return tuple(" ".join(i.split()).upper() for i in self.inci.replace(";", ",").split(",") if i.strip())

    def stesso_inci(self, altra):
        return altra is not None and self.inci_normalizzato == altra.inci_normalizzato

    @property
    def precedente(self):
        return VersioneFormula.objects.filter(formula=self.formula, numero__lt=self.numero).order_by("-numero").first()


class Campionatura(models.Model):
    class Esito(models.TextChoices):
        ATTESA = "attesa", "In attesa del cliente"
        APPROVATA = "approvata", "Approvata"
        MODIFICHE = "modifiche", "Modifiche richieste"
        RIFIUTATA = "rifiutata", "Rifiutata"

    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="campionature")
    numero = models.PositiveIntegerField(editable=False)
    versione_formula = models.ForeignKey(VersioneFormula, on_delete=models.PROTECT, related_name="campionature")
    data_invio = models.DateField(default=oggi)
    esito = models.CharField(max_length=20, choices=Esito.choices, default=Esito.ATTESA)
    feedback = models.TextField("feedback del cliente", blank=True)
    data_feedback = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["progetto", "numero"]
        verbose_name_plural = "campionature"

    def __str__(self):
        return f"Campionatura {self.numero} ({self.versione_formula})"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_numero(Campionatura.objects.filter(progetto=self.progetto))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return self.progetto.get_absolute_url()


class TestStabilita(models.Model):
    class Esito(models.TextChoices):
        IN_CORSO = "in_corso", "In corso"
        SUPERATA = "superata", "Superata"
        FALLITA = "fallita", "Fallita"

    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="stabilita")
    versione_formula = models.ForeignKey(VersioneFormula, on_delete=models.PROTECT, related_name="stabilita")
    data_inizio = models.DateField(default=oggi)
    durata_giorni = models.PositiveIntegerField(default=90)
    esito = models.CharField(max_length=20, choices=Esito.choices, default=Esito.IN_CORSO)
    data_esito = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, help_text="Es. compatibilità con il packaging, variazioni osservate.")

    class Meta:
        ordering = ["progetto", "data_inizio"]
        verbose_name = "test di stabilità"
        verbose_name_plural = "test di stabilità"

    def __str__(self):
        return f"Stabilità {self.versione_formula}"

    def get_absolute_url(self):
        return self.progetto.get_absolute_url()

    @property
    def data_fine_prevista(self):
        return self.data_inizio + timedelta(days=self.durata_giorni)

    @property
    def giorni_rimanenti(self):
        return (self.data_fine_prevista - oggi()).days

    @property
    def scaduta(self):
        return self.esito == self.Esito.IN_CORSO and self.giorni_rimanenti < 0


# --------------------------------------------------------------------------
# Quotazioni
# --------------------------------------------------------------------------
class Quotazione(models.Model):
    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        INVIATA = "inviata", "Inviata al cliente"
        ACCETTATA = "accettata", "Accettata"
        RIFIUTATA = "rifiutata", "Rifiutata"
        SUPERATA = "superata", "Superata"

    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="quotazioni")
    numero = models.PositiveIntegerField(editable=False)
    versione_formula = models.ForeignKey(
        VersioneFormula, null=True, blank=True, on_delete=models.PROTECT, related_name="quotazioni"
    )
    data = models.DateField(default=oggi)
    valida_fino = models.DateField(null=True, blank=True)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    commissione_pct = models.DecimalField(
        "commissione agente (%)", max_digits=5, decimal_places=2, default=0, help_text="Di solito tra 2 e 7, sul prezzo di vendita."
    )
    margine_obiettivo_pct = models.DecimalField(
        "margine obiettivo (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Sul prezzo di vendita, al netto di costi fissi e commissione. Serve a calcolare il prezzo suggerito.",
    )
    motivo = models.CharField(
        "motivo della revisione", max_length=250, blank=True, help_text="Es. aggiunto attivo, cambiato erogatore."
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["progetto", "-numero"]
        verbose_name_plural = "quotazioni"

    def __str__(self):
        return f"Quotazione {self.progetto.codice}/{self.numero}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_numero(Quotazione.objects.filter(progetto=self.progetto))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return self.progetto.get_absolute_url()

    @property
    def totale_costo(self):
        return sum((r.totale_costo for r in self.righe.all()), Decimal("0"))

    @property
    def totale_prezzo(self):
        return sum((r.totale_prezzo for r in self.righe.all()), Decimal("0"))

    @property
    def margine_pct(self):
        """Margine netto sul prezzo: tolti costo del produttore, costi fissi e commissione dell'agente."""
        prezzo = self.totale_prezzo
        return sum((r.margine_totale for r in self.righe.all()), Decimal("0")) / prezzo * 100 if prezzo else None


class RigaQuotazione(models.Model):
    class Tipo(models.TextChoices):
        PRODOTTO = "prodotto", "Prodotto finito"
        PACKAGING = "packaging", "Packaging eccedente / MOQ"
        UNA_TANTUM = "una_tantum", "Costo una tantum"

    quotazione = models.ForeignKey(Quotazione, on_delete=models.CASCADE, related_name="righe")
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.PRODOTTO)
    descrizione = models.CharField(max_length=250)
    quantita = models.PositiveIntegerField("quantità", default=1)
    costo_unitario = models.DecimalField(
        "costo dal produttore (€)", max_digits=12, decimal_places=4, default=0
    )
    costi_fissi = models.DecimalField(
        "nostri costi fissi per pezzo (€)", max_digits=12, decimal_places=4, default=0
    )
    prezzo_unitario = models.DecimalField(
        "prezzo al cliente (€)",
        max_digits=12,
        decimal_places=4,
        default=0,
        help_text="Lasciando 0 viene proposto il prezzo suggerito, se la quotazione ha un margine obiettivo.",
    )

    class Meta:
        ordering = ["pk"]
        verbose_name = "riga quotazione"
        verbose_name_plural = "righe quotazione"

    def __str__(self):
        return self.descrizione

    def get_absolute_url(self):
        return self.quotazione.get_absolute_url()

    @property
    def totale_costo(self):
        return self.quantita * self.costo_unitario

    @property
    def totale_prezzo(self):
        return self.quantita * self.prezzo_unitario

    def save(self, *args, **kwargs):
        if not self.prezzo_unitario and self.prezzo_suggerito:
            self.prezzo_unitario = self.prezzo_suggerito
        super().save(*args, **kwargs)

    @property
    def commissione_unitaria(self):
        return self.prezzo_unitario * self.quotazione.commissione_pct / 100

    @property
    def margine_unitario(self):
        return self.prezzo_unitario - self.costo_unitario - self.costi_fissi - self.commissione_unitaria

    @property
    def margine_totale(self):
        return self.quantita * self.margine_unitario

    @property
    def margine_pct(self):
        return self.margine_unitario / self.prezzo_unitario * 100 if self.prezzo_unitario else None

    @property
    def prezzo_suggerito(self):
        """Prezzo che lascia il margine obiettivo dopo costi fissi e commissione (entrambi % sul prezzo)."""
        q = self.quotazione
        if q.margine_obiettivo_pct is None:
            return None
        resto = 1 - (q.margine_obiettivo_pct + q.commissione_pct) / 100
        if resto <= 0:
            return None
        return ((self.costo_unitario + self.costi_fissi) / resto).quantize(Decimal("0.001"))


# --------------------------------------------------------------------------
# Packaging, artwork, distinta base
# --------------------------------------------------------------------------
class Componente(models.Model):
    """Componente generico a catalogo (non ancora personalizzato per un cliente)."""

    class Tipo(models.TextChoices):
        BOMBOLA = "bombola", "Bombola alluminio"
        FLACONE = "flacone", "Flacone plastica"
        TAPPO = "tappo", "Tappo / cap"
        EROGATORE = "erogatore", "Erogatore / dispenser"
        FOAMER = "foamer", "Foamer"
        ETICHETTA = "etichetta", "Etichetta"
        ASTUCCIO = "astuccio", "Astuccio / imballo"
        ALTRO = "altro", "Altro"

    codice = models.CharField(max_length=40, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    descrizione = models.CharField(max_length=200)
    materiale = models.CharField(max_length=80, blank=True)
    formato = models.CharField(max_length=80, blank=True, help_text="Es. 200 ml, Ø 35 mm.")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["tipo", "codice"]
        verbose_name_plural = "componenti"

    def __str__(self):
        return f"{self.codice} · {self.descrizione}"

    def get_absolute_url(self):
        return reverse("catalogo")


class Artwork(models.Model):
    class Stato(models.TextChoices):
        ATTESA_TDS = "attesa_tds", "In attesa del TDS dal produttore"
        BOZZA = "bozza", "TDS al cliente, artwork in preparazione"
        IN_APPROVAZIONE = "in_approvazione", "Al regolatorio del produttore"
        MODIFICHE = "modifiche", "Modifiche richieste dal regolatorio"
        APPROVATO = "approvato", "Definitivo"
        DA_RIFARE = "da_rifare", "Da rifare"
        SUPERATO = "superato", "Superato"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="artwork")
    progetto = models.ForeignKey(
        Progetto, null=True, blank=True, on_delete=models.SET_NULL, related_name="artwork"
    )
    nome = models.CharField(max_length=200, help_text="Es. Litografia bombola 200 ml, Etichetta retro.")
    versione = models.PositiveIntegerField(editable=False)
    versione_formula = models.ForeignKey(
        VersioneFormula,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artwork",
        verbose_name="INCI riportato (versione formula)",
        help_text="Versione della formula il cui INCI è stampato su questo artwork.",
    )
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    data_tds_richiesto = models.DateField("TDS richiesto al produttore il", null=True, blank=True)
    data_tds_ricevuto = models.DateField("TDS ricevuto il", null=True, blank=True)
    file_tds = models.FileField("file TDS", upload_to="tds/", blank=True)
    file = models.FileField("file artwork", upload_to="artwork/", blank=True)
    data_approvazione = models.DateField("definitivo dal", null=True, blank=True)
    costo_impianto = models.DecimalField(
        "costo impianti dal produttore (€)", max_digits=12, decimal_places=2, default=0,
        help_text="Costo fisso una tantum per un artwork nuovo (impianti di litografia, cliché…).",
    )
    prezzo_impianto = models.DecimalField("prezzo impianti al cliente (€)", max_digits=12, decimal_places=2, default=0)
    impianto_ordinato = models.BooleanField("impianti già ordinati al produttore", default=False)
    impianto_fatturato = models.BooleanField("impianti già fatturati al cliente", default=False)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["cliente", "nome", "versione"]
        verbose_name_plural = "artwork"

    def __str__(self):
        return f"{self.nome} v{self.versione}"

    def save(self, *args, **kwargs):
        if not self.versione:
            self.versione = _prossimo_numero(
                Artwork.objects.filter(cliente=self.cliente, nome=self.nome), "versione"
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return self.progetto.get_absolute_url() if self.progetto_id else self.cliente.get_absolute_url()


class Packaging(models.Model):
    """Componente personalizzato per un cliente (colore, decorazione, artwork).

    Un nuovo artwork (es. INCI cambiato) è un nuovo Packaging: così la giacenza
    stampata con il vecchio INCI resta distinta da quella nuova.
    """

    class Decorazione(models.TextChoices):
        NEUTRO = "neutro", "Neutro"
        COLORE = "colore", "Colorato in massa / pantone"
        LITOGRAFIA = "litografia", "Litografia"
        SERIGRAFIA = "serigrafia", "Serigrafia"
        ETICHETTA = "etichetta", "Etichetta applicata"

    codice = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="packaging")
    componente = models.ForeignKey(Componente, on_delete=models.PROTECT, related_name="personalizzazioni")
    descrizione = models.CharField(max_length=200)
    decorazione = models.CharField(max_length=20, choices=Decorazione.choices, default=Decorazione.NEUTRO)
    colore = models.CharField("colore / pantone", max_length=80, blank=True)
    artwork = models.ForeignKey(Artwork, null=True, blank=True, on_delete=models.PROTECT, related_name="packaging")
    riporta_inci = models.BooleanField(
        "riporta l'INCI", default=False, help_text="Spuntare se l'INCI è stampato su questo pezzo."
    )
    moq = models.PositiveIntegerField("lotto minimo (MOQ)", null=True, blank=True)
    costo_unitario = models.DecimalField(
        "costo dal produttore (€/pezzo)", max_digits=12, decimal_places=4, null=True, blank=True
    )
    prezzo_unitario = models.DecimalField(
        "prezzo di rifatturazione al cliente (€/pezzo)", max_digits=12, decimal_places=4, null=True, blank=True
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["cliente", "codice"]
        verbose_name_plural = "packaging"

    def __str__(self):
        return f"{self.codice} · {self.descrizione}"

    def save(self, *args, **kwargs):
        if not self.codice:
            self.codice = _prossimo_codice(Packaging, "PKG")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalogo")

    @property
    def versione_formula_stampata(self):
        return self.artwork.versione_formula if self.riporta_inci and self.artwork_id else None

    def giacenza(self, produttore=None):
        qs = self.movimenti.all()
        if produttore is not None:
            qs = qs.filter(produttore=produttore)
        return qs.aggregate(q=Sum("quantita"))["q"] or 0


class Prodotto(models.Model):
    """SKU venduto al cliente: formula (in una versione) + distinta base."""

    codice = models.CharField("codice SKU", max_length=40, unique=True)
    nome = models.CharField(max_length=200)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="prodotti")
    progetto = models.ForeignKey(
        Progetto, null=True, blank=True, on_delete=models.SET_NULL, related_name="prodotti"
    )
    versione_formula = models.ForeignKey(
        VersioneFormula,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="prodotti",
        verbose_name="formula da produrre",
        help_text="Versione che verrà usata alla prossima produzione.",
    )
    formato = models.CharField(max_length=80, blank=True, help_text="Es. 200 ml.")
    hs_code = models.CharField("HS code", max_length=20, blank=True, help_text="Voce doganale, es. 33049900.")
    pezzi_per_cartone = models.PositiveIntegerField(null=True, blank=True)
    un_numero = models.CharField(
        "numero UN", max_length=10, blank=True, help_text="Solo per merci pericolose, es. UN 1950. Vuoto se non pericoloso."
    )
    un_denominazione = models.CharField("denominazione di trasporto", max_length=200, blank=True, help_text="Proper shipping name, es. AEROSOL.")
    un_classe = models.CharField("classe di pericolo", max_length=20, blank=True, help_text="Es. 2.1; aggiungere il gruppo d'imballaggio se previsto (9, III).")
    un_ems = models.CharField("EmS", max_length=20, blank=True, help_text="Es. F-D, S-U.")
    quantita_limitata = models.BooleanField("spedito in quantità limitata (LQ)", default=False)
    imballo_interno = models.CharField(
        "imballo interno", max_length=120, blank=True, help_text="In inglese, es. metal inners x 150 mL net each."
    )
    prossima_consegna = models.DateField(
        "prossima consegna prevista",
        null=True,
        blank=True,
        help_text="Dal forecast del cliente: serve a ricordare di chiedere l'ordine per tempo.",
    )
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["cliente", "codice"]
        verbose_name_plural = "prodotti"

    def __str__(self):
        return f"{self.codice} · {self.nome}"

    def get_absolute_url(self):
        return reverse("prodotto", args=[self.pk])


class RigaDistinta(models.Model):
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="distinta")
    packaging = models.ForeignKey(Packaging, on_delete=models.PROTECT, related_name="righe_distinta")
    quantita_per_pezzo = models.DecimalField("quantità per pezzo", max_digits=8, decimal_places=3, default=1)
    etichetta_correttiva = models.BooleanField(
        default=False,
        help_text="Il cliente è stato avvisato e l'INCI aggiornato viene applicato con un'etichetta sul retro.",
    )

    class Meta:
        ordering = ["pk"]
        unique_together = [("prodotto", "packaging")]
        verbose_name = "riga distinta base"
        verbose_name_plural = "righe distinta base"

    def __str__(self):
        return f"{self.prodotto.codice} ← {self.packaging.codice}"

    def get_absolute_url(self):
        return self.prodotto.get_absolute_url()


# --------------------------------------------------------------------------
# Ordini e magazzino packaging
# --------------------------------------------------------------------------
class OrdineCliente(models.Model):
    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        INVIATA = "inviata", "Conferma inviata"
        ACCETTATA = "accettata", "Accettata dal cliente"
        IN_PRODUZIONE = "in_produzione", "In produzione"
        PRONTO = "pronto", "Merce pronta"
        CONSEGNATO = "consegnato", "Spedito"
        ANNULLATO = "annullato", "Annullato"

    numero = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ordini")
    progetto = models.ForeignKey(Progetto, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordini")
    produttore = models.ForeignKey(Produttore, on_delete=models.PROTECT, related_name="ordini")
    data = models.DateField(default=oggi)
    data_consegna_prevista = models.DateField(null=True, blank=True)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    riferimento_cliente = models.CharField(max_length=120, blank=True, help_text="Numero d'ordine del cliente.")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "ordine cliente"
        verbose_name_plural = "ordini cliente"

    def __str__(self):
        return self.numero

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_codice(OrdineCliente, "OC", "numero")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("ordine", args=[self.pk])

    @property
    def totale(self):
        return sum((r.totale for r in self.righe.all()), Decimal("0"))


class RigaOrdine(models.Model):
    ordine = models.ForeignKey(OrdineCliente, on_delete=models.CASCADE, related_name="righe")
    prodotto = models.ForeignKey(Prodotto, on_delete=models.PROTECT, related_name="righe_ordine")
    quantita = models.PositiveIntegerField("quantità")
    prezzo_unitario = models.DecimalField("prezzo unitario (€)", max_digits=12, decimal_places=4, default=0)
    lotto = models.CharField("lotto di produzione", max_length=60, blank=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "riga ordine"
        verbose_name_plural = "righe ordine"

    def __str__(self):
        return f"{self.ordine.numero} · {self.prodotto.codice}"

    def get_absolute_url(self):
        return self.ordine.get_absolute_url()

    @property
    def totale(self):
        return self.quantita * self.prezzo_unitario


class MovimentoPackaging(models.Model):
    """Carichi e scarichi del packaging di proprietà del cliente, in deposito dal produttore."""

    class Tipo(models.TextChoices):
        CARICO = "carico", "Carico (acquisto)"
        CONSUMO = "consumo", "Consumo in produzione"
        SCARTO = "scarto", "Scarto / obsoleto"
        RETTIFICA = "rettifica", "Rettifica inventario (+/−)"

    packaging = models.ForeignKey(Packaging, on_delete=models.PROTECT, related_name="movimenti")
    produttore = models.ForeignKey(
        Produttore, on_delete=models.PROTECT, related_name="movimenti", verbose_name="in deposito presso"
    )
    data = models.DateField(default=oggi)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CARICO)
    quantita = models.IntegerField("quantità", help_text="Inserire un numero positivo; il segno dipende dal tipo.")
    ordine = models.ForeignKey(
        OrdineCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="movimenti"
    )
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "movimento packaging"
        verbose_name_plural = "movimenti packaging"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.quantita} {self.packaging.codice}"

    def save(self, *args, **kwargs):
        if self.tipo == self.Tipo.CARICO:
            self.quantita = abs(self.quantita)
        elif self.tipo in (self.Tipo.CONSUMO, self.Tipo.SCARTO):
            self.quantita = -abs(self.quantita)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("magazzino")


# --------------------------------------------------------------------------
# Documenti: ordine d'acquisto al produttore, DDT, pre-fattura
# --------------------------------------------------------------------------
DUE = Decimal("0.01")


def euro(valore):
    from decimal import ROUND_HALF_UP

    return Decimal(valore).quantize(DUE, rounding=ROUND_HALF_UP)


class Azienda(models.Model):
    """Dati della nostra azienda, usati su documenti e pre-fatture (un solo record)."""

    ragione_sociale = models.CharField(max_length=200)
    partita_iva = models.CharField("partita IVA", max_length=30, blank=True, help_text="Senza il prefisso IT.")
    codice_fiscale = models.CharField(max_length=30, blank=True)
    regime_fiscale = models.CharField(max_length=4, default="RF01", help_text="Codice FatturaPA: RF01 = ordinario.")
    indirizzo = models.CharField(max_length=250, blank=True)
    cap = models.CharField("CAP", max_length=10, blank=True)
    comune = models.CharField(max_length=80, blank=True)
    provincia = models.CharField(max_length=2, blank=True)
    codice_paese = models.CharField("codice paese", max_length=2, default="IT")
    iban = models.CharField("IBAN", max_length=34, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    logo = models.FileField(
        "logo per la carta intestata", upload_to="azienda/", blank=True, help_text="Immagine PNG, JPG o SVG."
    )
    contatto_emergenza = models.TextField(
        "contatto d'emergenza 24h", blank=True, help_text="Per la dichiarazione merci pericolose: nome, telefoni, email."
    )
    dichiarante = models.CharField(
        "dichiarante merci pericolose", max_length=120, blank=True, help_text="Nome e qualifica, es. Mario Rossi / CEO."
    )
    piede_documenti = models.TextField(
        "piè di pagina dei documenti", blank=True,
        help_text="Es. capitale sociale, REA, sito web. Compare in fondo a ogni pagina dei PDF.",
    )

    class Meta:
        verbose_name = "dati azienda"
        verbose_name_plural = "dati azienda"

    def __str__(self):
        return self.ragione_sociale

    def get_absolute_url(self):
        return reverse("azienda")

    @classmethod
    def corrente(cls):
        return cls.objects.first() or cls(ragione_sociale=settings.NOME_AZIENDA)


class OrdineAcquisto(models.Model):
    """Ordine al produttore full service: prodotto finito più packaging da tenere in deposito."""

    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        INVIATO = "inviato", "Inviato al produttore"
        CONFERMATO = "confermato", "Confermato dal produttore"
        RICEVUTO = "ricevuto", "Merce consegnata"
        ANNULLATO = "annullato", "Annullato"

    numero = models.CharField(max_length=20, unique=True, blank=True)
    produttore = models.ForeignKey(Produttore, on_delete=models.PROTECT, related_name="ordini_acquisto")
    ordine = models.ForeignKey(
        OrdineCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordini_acquisto",
        verbose_name="ordine cliente",
    )
    data = models.DateField(default=oggi)
    data_consegna_richiesta = models.DateField(null=True, blank=True)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    ddt_fornitore = models.CharField("DDT del produttore (numero e data)", max_length=120, blank=True)
    fattura_fornitore = models.CharField("fattura del produttore (numero e data)", max_length=120, blank=True)
    importo_fattura_fornitore = models.DecimalField(
        "importo fattura del produttore (€)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "ordine d'acquisto"
        verbose_name_plural = "ordini d'acquisto"

    def __str__(self):
        return self.numero

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_codice(OrdineAcquisto, "OA", "numero")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("acquisto", args=[self.pk])

    @property
    def totale(self):
        return sum((r.totale for r in self.righe.all()), Decimal("0"))

    @property
    def differenza_fattura(self):
        """Fattura del produttore meno totale dell'ordine; None se non c'è fattura o se coincidono."""
        if self.importo_fattura_fornitore is None:
            return None
        diff = self.importo_fattura_fornitore - euro(self.totale)
        return diff if abs(diff) >= Decimal("0.01") else None


class TipoRiga(models.TextChoices):
    PRODOTTO = "prodotto", "Prodotto finito"
    PACKAGING = "packaging", "Packaging in deposito"
    IMPIANTI = "impianti", "Impianti per nuovo artwork"
    ALTRO = "altro", "Altro"


class RigaAcquisto(models.Model):
    ordine_acquisto = models.ForeignKey(OrdineAcquisto, on_delete=models.CASCADE, related_name="righe")
    tipo = models.CharField(max_length=20, choices=TipoRiga.choices, default=TipoRiga.PRODOTTO)
    descrizione = models.CharField(max_length=250)
    quantita = models.PositiveIntegerField("quantità", default=1)
    costo_unitario = models.DecimalField("costo unitario (€)", max_digits=12, decimal_places=4, default=0)

    class Meta:
        ordering = ["pk"]
        verbose_name = "riga ordine d'acquisto"
        verbose_name_plural = "righe ordine d'acquisto"

    def __str__(self):
        return self.descrizione

    def get_absolute_url(self):
        return self.ordine_acquisto.get_absolute_url()

    @property
    def totale(self):
        return self.quantita * self.costo_unitario


class DDT(models.Model):
    numero = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ddt")
    ordine = models.ForeignKey(
        OrdineCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="ddt",
        verbose_name="ordine cliente",
    )
    data = models.DateField(default=oggi)
    luogo_partenza = models.CharField("luogo di partenza della merce", max_length=250, blank=True)
    destinazione = models.CharField(max_length=250, blank=True)
    causale = models.CharField(max_length=80, default="Vendita")
    vettore = models.CharField(max_length=120, blank=True)
    porto = models.CharField(max_length=40, blank=True, help_text="Es. franco, assegnato.")
    colli = models.PositiveIntegerField(null=True, blank=True)
    peso_kg = models.DecimalField("peso lordo (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    peso_netto_kg = models.DecimalField("peso netto (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    aspetto = models.CharField("aspetto esteriore dei beni", max_length=80, blank=True, help_text="Es. cartoni su pallet.")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "DDT"
        verbose_name_plural = "DDT"

    def __str__(self):
        return self.numero

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_codice(DDT, "DDT", "numero")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("ddt", args=[self.pk])


class RigaDDT(models.Model):
    ddt = models.ForeignKey(DDT, on_delete=models.CASCADE, related_name="righe")
    codice = models.CharField(max_length=40, blank=True)
    descrizione = models.CharField(max_length=250)
    quantita = models.PositiveIntegerField("quantità")
    lotto = models.CharField("lotto di produzione", max_length=60, blank=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "riga DDT"
        verbose_name_plural = "righe DDT"

    def __str__(self):
        return self.descrizione

    def get_absolute_url(self):
        return self.ddt.get_absolute_url()


class PreFattura(models.Model):
    """Bozza di fattura da importare nel software di contabilità, che assegna il numero definitivo."""

    class Stato(models.TextChoices):
        BOZZA = "bozza", "Bozza"
        ESPORTATA = "esportata", "Esportata"
        REGISTRATA = "registrata", "Registrata in contabilità"

    class Natura(models.TextChoices):
        NESSUNA = "", "Imponibile (IVA applicata)"
        N3_1 = "N3.1", "N3.1 · Non imponibile, esportazione"
        N3_2 = "N3.2", "N3.2 · Non imponibile, cessione intracomunitaria"
        N3_5 = "N3.5", "N3.5 · Non imponibile, dichiarazione d'intento"
        N2_1 = "N2.1", "N2.1 · Non soggetta, artt. da 7 a 7-septies"

    numero = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="prefatture")
    ordine = models.ForeignKey(
        OrdineCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="prefatture",
        verbose_name="ordine cliente",
    )
    ddt = models.ForeignKey(DDT, null=True, blank=True, on_delete=models.SET_NULL, related_name="prefatture", verbose_name="DDT")
    data = models.DateField(default=oggi)
    aliquota_iva = models.DecimalField("aliquota IVA (%)", max_digits=5, decimal_places=2, default=Decimal("22"))
    natura = models.CharField("natura IVA", max_length=4, choices=Natura.choices, blank=True, help_text="Da indicare solo con aliquota 0.")
    pagamento = models.CharField("condizioni di pagamento", max_length=120, blank=True)
    data_scadenza = models.DateField("scadenza pagamento", null=True, blank=True)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    numero_fattura = models.CharField(
        "numero fattura definitivo", max_length=40, blank=True, help_text="Assegnato dal software di contabilità."
    )
    data_fattura = models.DateField("data fattura definitiva", null=True, blank=True)
    pagata = models.BooleanField("pagamento ricevuto", default=False)
    data_pagamento = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "pre-fattura"
        verbose_name_plural = "pre-fatture"

    def __str__(self):
        return self.numero

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_codice(PreFattura, "PF", "numero")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("prefattura", args=[self.pk])

    @property
    def imponibile(self):
        return sum((r.totale for r in self.righe.all()), Decimal("0.00"))

    @property
    def imposta(self):
        return euro(self.imponibile * self.aliquota_iva / 100)

    @property
    def totale(self):
        return self.imponibile + self.imposta


class RigaPreFattura(models.Model):
    prefattura = models.ForeignKey(PreFattura, on_delete=models.CASCADE, related_name="righe")
    tipo = models.CharField(max_length=20, choices=TipoRiga.choices, default=TipoRiga.PRODOTTO)
    codice = models.CharField(max_length=40, blank=True)
    descrizione = models.CharField(max_length=250)
    quantita = models.PositiveIntegerField("quantità", default=1)
    prezzo_unitario = models.DecimalField("prezzo unitario (€)", max_digits=12, decimal_places=4, default=0)

    class Meta:
        ordering = ["pk"]
        verbose_name = "riga pre-fattura"
        verbose_name_plural = "righe pre-fattura"

    def __str__(self):
        return self.descrizione

    def get_absolute_url(self):
        return self.prefattura.get_absolute_url()

    @property
    def totale(self):
        return euro(self.quantita * self.prezzo_unitario)


# --------------------------------------------------------------------------
# Listino prezzi e promemoria
# --------------------------------------------------------------------------
class VoceListino(models.Model):
    """Prezzo di riferimento per fare un'offerta senza richiedere un nuovo brief al produttore."""

    produttore = models.ForeignKey(Produttore, on_delete=models.PROTECT, related_name="listino")
    formula = models.ForeignKey(Formula, null=True, blank=True, on_delete=models.SET_NULL, related_name="listino")
    tipo = models.CharField(max_length=20, choices=RigaQuotazione.Tipo.choices, default=RigaQuotazione.Tipo.PRODOTTO)
    descrizione = models.CharField(max_length=250, help_text="Formula e packaging, es. Mousse 200 ml, bombola litografata.")
    quantita_minima = models.PositiveIntegerField("da (pezzi)", default=1, help_text="Scaglione: il prezzo vale da questa quantità.")
    costo_unitario = models.DecimalField("costo dal produttore (€)", max_digits=12, decimal_places=4, default=0)
    prezzo_unitario = models.DecimalField("prezzo consigliato al cliente (€)", max_digits=12, decimal_places=4, default=0)
    valido_dal = models.DateField(default=oggi)
    valido_fino = models.DateField(null=True, blank=True, help_text="Lasciare vuoto se non ha scadenza.")
    origine = models.ForeignKey(
        RigaQuotazione, null=True, blank=True, on_delete=models.SET_NULL, related_name="voci_listino", editable=False
    )
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["produttore", "descrizione", "quantita_minima"]
        verbose_name = "voce di listino"
        verbose_name_plural = "voci di listino"

    def __str__(self):
        return f"{self.descrizione} (da {self.quantita_minima} pz)"

    def get_absolute_url(self):
        return reverse("listino")

    @property
    def scaduta(self):
        return self.valido_fino is not None and self.valido_fino < oggi()

    @property
    def margine_pct(self):
        return (
            (self.prezzo_unitario - self.costo_unitario) / self.prezzo_unitario * 100 if self.prezzo_unitario else None
        )


class Promemoria(models.Model):
    """Cosa fare e entro quando, su un cliente o un progetto (richiamare, sollecitare, inviare...)."""

    testo = models.CharField("cosa fare", max_length=250)
    scadenza = models.DateField(default=oggi)
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.CASCADE, related_name="promemoria")
    progetto = models.ForeignKey(Progetto, null=True, blank=True, on_delete=models.CASCADE, related_name="promemoria")
    assegnato_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="promemoria"
    )
    fatto = models.BooleanField(default=False)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fatto", "scadenza", "pk"]
        verbose_name = "promemoria"
        verbose_name_plural = "promemoria"

    def __str__(self):
        return self.testo

    def save(self, *args, **kwargs):
        if self.progetto_id and not self.cliente_id:
            self.cliente = self.progetto.cliente
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.progetto_id:
            return self.progetto.get_absolute_url()
        return self.cliente.get_absolute_url() if self.cliente_id else reverse("dashboard")

    @property
    def scaduto(self):
        return not self.fatto and self.scadenza < oggi()


# --------------------------------------------------------------------------
# Brief al produttore
# --------------------------------------------------------------------------
class Brief(models.Model):
    """Richiesta d'offerta al produttore, compilata sul suo modulo Word."""

    class Stato(models.TextChoices):
        BOZZA = "bozza", "In compilazione"
        INVIATO = "inviato", "Inviato al produttore"
        RISPOSTA = "risposta", "Offerta del produttore ricevuta"

    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="brief_produttore")
    numero = models.PositiveIntegerField(editable=False)
    modello = models.FileField(upload_to="brief/", editable=False)
    valori = models.JSONField(default=dict, blank=True, editable=False)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.BOZZA)
    data_invio = models.DateField(null=True, blank=True)
    risposta = models.FileField("offerta ricevuta dal produttore", upload_to="brief/", blank=True)
    note = models.TextField(blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["progetto", "-numero"]
        verbose_name = "brief"
        verbose_name_plural = "brief"

    def __str__(self):
        return f"Brief {self.progetto.codice}/{self.numero}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_numero(Brief.objects.filter(progetto=self.progetto))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("brief", args=[self.pk])


# --------------------------------------------------------------------------
# Spedizioni: packing list e dichiarazione multimodale merci pericolose
# --------------------------------------------------------------------------
class Spedizione(models.Model):
    numero = models.CharField(max_length=20, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="spedizioni")
    ordine = models.ForeignKey(
        OrdineCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="spedizioni", verbose_name="ordine cliente"
    )
    data = models.DateField(default=oggi)
    riferimenti = models.CharField("riferimenti (fatture, DDT)", max_length=250, blank=True, help_text="Es. Invoices n. 1 dated 24/06/2026.")
    resa = models.CharField("resa (Incoterm)", max_length=40, default="EXW")
    vettore = models.CharField("vettore / spedizioniere", max_length=120, blank=True)
    nave_viaggio = models.CharField("nave e viaggio / volo", max_length=120, blank=True)
    container = models.CharField("container (tipo, numero, tara)", max_length=120, blank=True)
    sigillo = models.CharField(max_length=60, blank=True)
    porto_imbarco = models.CharField("porto / luogo d'imbarco", max_length=120, blank=True)
    porto_sbarco = models.CharField("porto / luogo di sbarco", max_length=120, blank=True)
    destinazione = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name = "spedizione"
        verbose_name_plural = "spedizioni"

    def __str__(self):
        return self.numero

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_codice(Spedizione, "SP", "numero")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("spedizione", args=[self.pk])

    @property
    def totali(self):
        colli = list(self.colli.all())
        return {
            "pallet": len(colli),
            "lordo": sum((c.peso_lordo_kg or 0 for c in colli), Decimal("0")),
            "netto": sum((c.peso_netto_kg or 0 for c in colli), Decimal("0")),
            "pezzi": sum(c.quantita or 0 for c in colli),
            "cartoni": sum(c.cartoni or 0 for c in colli),
        }

    def merci_pericolose(self):
        """Righe della dichiarazione multimodale: una per merce pericolosa, con colli e masse sommati."""
        gruppi = {}
        for c in self.colli.select_related("prodotto"):
            if not c.un:
                continue
            chiave = c.prodotto_id or c.descrizione
            g = gruppi.setdefault(chiave, {"collo": c, "prodotto": c.prodotto, "lordo": Decimal("0"), "netto": Decimal("0"), "cartoni": 0, "pallet": 0})
            g["lordo"] += c.peso_lordo_kg or 0
            g["netto"] += c.peso_netto_kg or 0
            g["cartoni"] += c.cartoni or 0
            g["pallet"] += 1
        return list(gruppi.values())


class Collo(models.Model):
    """Un pallet (o collo) della spedizione."""

    spedizione = models.ForeignKey(Spedizione, on_delete=models.CASCADE, related_name="colli")
    numero = models.PositiveIntegerField("pallet n.", editable=False)
    prodotto = models.ForeignKey(Prodotto, null=True, blank=True, on_delete=models.PROTECT, related_name="colli")
    descrizione = models.CharField(max_length=200, blank=True, help_text="Compilata dal prodotto se lasciata vuota.")
    quantita = models.PositiveIntegerField("quantità (pezzi)", null=True, blank=True)
    lotto = models.CharField(max_length=60, blank=True)
    cartoni = models.PositiveIntegerField("numero di cartoni", null=True, blank=True)
    peso_lordo_kg = models.DecimalField("peso lordo (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    peso_netto_kg = models.DecimalField("peso netto (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    dimensioni = models.CharField("dimensioni pallet (cm)", max_length=40, blank=True, help_text="Es. 120x80x117.")
    un = models.CharField("numero UN", max_length=10, blank=True, help_text="Vuoto se non pericoloso; preso dal prodotto se lasciato vuoto.")
    descrizione_adr = models.TextField(
        "descrizione per la dichiarazione merci pericolose",
        blank=True,
        help_text="Solo per merci senza scheda prodotto (es. bulk): UN, denominazione, classe, EmS, imballi. In inglese.",
    )

    class Meta:
        ordering = ["spedizione", "numero"]
        verbose_name = "pallet"
        verbose_name_plural = "pallet"

    def __str__(self):
        return f"{self.spedizione.numero} · pallet {self.numero}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = _prossimo_numero(Collo.objects.filter(spedizione=self.spedizione))
        if self.prodotto_id:
            self.descrizione = self.descrizione or " ".join(x for x in (self.prodotto.nome, self.prodotto.formato) if x)
            self.un = self.un or self.prodotto.un_numero.replace(" ", "")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return self.spedizione.get_absolute_url()


# --------------------------------------------------------------------------
# Accessi
# --------------------------------------------------------------------------
class Profilo(models.Model):
    """Limiti di accesso di un utente: utente del produttore, oppure sezioni nascoste a un utente interno."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profilo")
    produttore = models.ForeignKey(
        Produttore, null=True, blank=True, on_delete=models.CASCADE, related_name="accessi",
        help_text="Se indicato, l'utente vede solo l'area riservata di questo produttore.",
    )
    sezioni_nascoste = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "profilo di accesso"
        verbose_name_plural = "profili di accesso"

    def __str__(self):
        return str(self.user)

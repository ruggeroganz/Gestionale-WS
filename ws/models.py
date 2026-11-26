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
        LEAD = "lead", "Lead / Brief"
        QUOTAZIONE = "quotazione", "Quotazione"
        CAMPIONATURA = "campionatura", "Campionatura"
        STABILITA = "stabilita", "Stabilità"
        PACKAGING = "packaging", "Artwork e packaging"
        ORDINE = "ordine", "Ordine"
        PRODUZIONE = "produzione", "Produzione"
        CONSEGNATO = "consegnato", "Consegnato"

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
        prezzo = self.totale_prezzo
        return (prezzo - self.totale_costo) / prezzo * 100 if prezzo else None


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
    prezzo_unitario = models.DecimalField("prezzo al cliente (€)", max_digits=12, decimal_places=4, default=0)

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

    @property
    def margine_pct(self):
        return (
            (self.prezzo_unitario - self.costo_unitario) / self.prezzo_unitario * 100
            if self.prezzo_unitario
            else None
        )


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
        BOZZA = "bozza", "Bozza"
        IN_APPROVAZIONE = "in_approvazione", "In approvazione"
        APPROVATO = "approvato", "Approvato"
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
    file = models.FileField(upload_to="artwork/", blank=True)
    data_approvazione = models.DateField(null=True, blank=True)
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
        CONSEGNATO = "consegnato", "Consegnato"
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


class TipoRiga(models.TextChoices):
    PRODOTTO = "prodotto", "Prodotto finito"
    PACKAGING = "packaging", "Packaging in deposito"
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
    peso_kg = models.DecimalField("peso (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
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

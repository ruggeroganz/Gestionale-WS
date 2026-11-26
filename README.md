# Gestionale WS

Gestionale per un'azienda di private label cosmetico che lavora con produttori
terzisti full service. Segue ogni prodotto dal primo brief alla consegna e ai
riordini: quotazioni, campionature, stabilità, artwork, distinta base, ordini e
magazzino del packaging di proprietà dei clienti.

## Avvio in locale

```bash
pip install -r requirements.txt
```

```bash
python manage.py migrate
```

```bash
python manage.py dati_demo
```

```bash
python manage.py runserver
```

Poi aprire http://localhost:8000. `dati_demo` è facoltativo: crea dati inventati
e gli utenti `commerciale`, `customer`, `amministrazione` e `admin`
(password `demo1234`, da non usare in produzione). Senza dati demo, creare il
primo utente con `python manage.py createsuperuser`.

Test: `python manage.py test`.

## Come è organizzato

| File | Contenuto |
| --- | --- |
| `ws/models.py` | Modello dati |
| `ws/flusso.py` | Regole: cancelli di fase, piano a ritroso, coerenza INCI, fabbisogno packaging |
| `ws/views.py` | Pagine e form generico di inserimento/modifica |
| `ws/templates/ws/` | Interfaccia |
| `ws/management/commands/dati_demo.py` | Dati di esempio |

### Il flusso del progetto

Lead → Quotazione → Campionatura → Stabilità → Artwork e packaging → Ordine →
Produzione → Consegnato. Si avanza solo quando le condizioni della fase sono
soddisfatte:

- **Quotazione**: serve una quotazione accettata dal cliente.
- **Campionatura**: serve una campionatura approvata. Passando a Stabilità il
  test (90 giorni) parte in automatico sulla formula approvata.
- **Stabilità**: il packaging non parte finché la stabilità non è superata. Se
  fallisce, il progetto torna in Campionatura e gli artwork con quell'INCI
  vengono segnati «da rifare».
- **Artwork e packaging**: artwork approvato con l'INCI della formula
  approvata, prodotto con distinta base, quotazione accettata.

Il piano a ritroso calcola le scadenze dalla data di consegna richiesta (lead
time del produttore, 150 giorni di default, più 90 di stabilità).

### La catena formula → INCI → artwork → packaging

Ogni versione di formula ha il suo INCI. Ogni artwork dichiara quale versione
riporta. Ogni packaging personalizzato (es. bombola litografata) punta a un
artwork, e la giacenza è per packaging. Se la formula da produrre di un
prodotto ha un INCI diverso da quello stampato sul packaging in distinta, il
gestionale lo segnala su cruscotto, prodotto, ordine e magazzino, con tre vie
d'uscita: continuare con la formula precedente fino a esaurimento, etichetta
correttiva (cliente avvisato), oppure scarto della giacenza.

### Magazzino packaging

Il packaging è acquistato dal produttore, fatturato a WS e rifatturato al
cliente: il residuo resta di proprietà del cliente, in deposito presso il
produttore. Per ogni ordine il fabbisogno è distinta base × quantità, meno la
giacenza presso quel produttore, arrotondato al lotto minimo (MOQ).

## Non ancora incluso

Ordine d'acquisto al produttore, DDT e fatture; permessi differenziati per
ruolo (oggi ogni utente autenticato vede e modifica tutto); listino con
scaglioni gestiti a parte (oggi è lo storico delle quotazioni); configurazione
per la messa in produzione (database PostgreSQL, HTTPS, backup).

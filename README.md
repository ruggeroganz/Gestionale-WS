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

## Messa online

Il progetto gira su qualunque hosting che esegua un container Docker (o
un'app Python) con un database PostgreSQL. L'avvio (`avvio.sh`) aggiorna il
database, crea il primo utente se non ce ne sono e lancia il server.

Variabili d'ambiente da impostare sull'hosting:

| Variabile | Valore |
| --- | --- |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_SECRET_KEY` | una stringa lunga e casuale, da tenere segreta |
| `DJANGO_ALLOWED_HOSTS` | l'indirizzo del sito, es. `gestionale.miazienda.it` |
| `DATABASE_URL` | l'indirizzo del database PostgreSQL fornito dall'hosting |
| `ADMIN_PASSWORD` | password del primo utente `admin` (usata solo al primo avvio) |
| `MEDIA_ROOT` | cartella su disco persistente per gli allegati, es. `/var/data` |

Senza Docker: `pip install -r requirements.txt`, poi
`python manage.py collectstatic --noinput` e `./avvio.sh`.

Al primo accesso entrare come `admin`, cambiare la password, compilare «Dati
azienda» e creare gli utenti da «Amministrazione → Utenti», assegnando a
ciascuno il gruppo del suo ruolo. Gli allegati (artwork) sono visibili solo
dopo l'accesso. Vanno previsti backup automatici del database e del disco
degli allegati: di solito sono un'opzione dell'hosting.

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

### Documenti

Dall'ordine cliente si generano, già compilati e poi modificabili:

- **Ordine d'acquisto al produttore**: prodotto finito (costo dalla quotazione
  accettata) più il packaging acquistato in eccedenza, da tenere in deposito.
  Sullo stesso ordine si annotano DDT e fattura ricevuti dal produttore.
- **DDT** verso il cliente.
- **Pre-fattura**: prodotto finito più rifatturazione del packaging residuo.
  Non è una fattura: si scarica in **XML FatturaPA 1.2** (o in CSV) e si importa
  nel software di contabilità, che assegna il numero definitivo e la invia allo
  SDI. Numero e data definitivi si riportano poi sulla pre-fattura. Prima
  dell'esportazione la pagina elenca i dati mancanti (partita IVA, codice SDI,
  indirizzo, prezzi a zero). I dati dell'azienda emittente si inseriscono in
  «Dati azienda».

L'XML segue il tracciato ufficiale ma non è stato ancora validato con lo schema
XSD dell'Agenzia delle Entrate né provato con un'importazione reale: va fatto
un test con il commercialista prima di usarlo.

### Listino, offerte, riordini, promemoria

- **Listino prezzi**: voci con produttore, formula, scaglione di quantità, costo,
  prezzo consigliato e validità. Si compilano a mano o con «salva nel listino»
  dallo storico delle quotazioni; con «+ dal listino» una voce entra in una
  nuova quotazione senza richiedere un brief al produttore.
- **Quotazioni**: «nuova versione» copia le voci in una bozza da modificare;
  «offerta» è il documento per il cliente, con i soli prezzi di vendita.
- **Riordino**: dal prodotto, crea un ordine in bozza con quantità, prezzo e
  produttore dell'ultimo ordine; il fabbisogno tiene conto del packaging residuo.
- **Promemoria**: cose da fare con scadenza e assegnatario, su cliente o
  progetto, raccolte nel cruscotto.
- **Ricerca** su clienti, progetti, prodotti, formule, packaging e documenti.

### Ruoli

Tutti gli utenti consultano tutto; inserire e modificare dipende dal gruppo
(valori iniziali in `ws/ruoli.py`, poi modificabili dal pannello di
amministrazione; `python manage.py imposta_ruoli` li ripristina).

| Ruolo | Può inserire e modificare |
| --- | --- |
| Commerciale | Clienti, progetti, quotazioni, campionature, ordini cliente |
| Customer service e acquisti | Tutto tranne pre-fatture e dati azienda |
| Amministrazione | Clienti, produttori, dati azienda, pre-fatture, fattura del produttore sugli ordini d'acquisto |

## Non ancora incluso

Note di credito; pulsanti nascosti in base al ruolo (oggi l'operazione non
permessa viene rifiutata con un messaggio); configurazione per la messa in
produzione (database PostgreSQL, HTTPS, backup).

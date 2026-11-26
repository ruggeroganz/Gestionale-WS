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

Brief → Offerta → Campionatura → Stabilità e artwork → Packaging in produzione →
Produzione → Spedizione e fattura → Concluso. Si avanza solo quando le
condizioni della fase sono soddisfatte:

- **Offerta**: serve una quotazione accettata dal cliente.
- **Campionatura**: serve una campionatura approvata. Per una formula esistente
  senza campionatura la fase viene saltata e si indica la formula sul progetto.
- **Stabilità e artwork**: mentre corre la stabilità (90 giorni, solo per le
  formule nuove, avviata in automatico) arrivano l'ordine del cliente, il TDS
  dal produttore e l'artwork. Il packaging parte solo con stabilità superata,
  ordine confermato, artwork definitivo approvato dal regolatorio e prodotto
  con distinta base. Se la stabilità fallisce il progetto torna in
  Campionatura e gli artwork con quell'INCI vengono segnati «da rifare».
- **Packaging in produzione**: serve il campione di stampa approvato dal cliente.
- **Produzione**: si esce quando il produttore comunica la merce pronta.
- **Spedizione e fattura**: DDT, ordine spedito, fattura emessa, pagamento ricevuto.

Il piano a ritroso calcola le scadenze dalla data di consegna richiesta, con il
lead time del packaging indicato sul progetto (150 giorni per le bombole, 120
per flaconi e foamer) più i 90 giorni di stabilità quando serve.

Il cruscotto raccoglie le scadenze: pagamenti da verificare, riordini da
sollecitare al cliente (dalla «prossima consegna prevista» del prodotto, un
lead time prima), TDS fermi da più di due settimane, fatture del produttore
diverse dall'ordine d'acquisto.

### Brief al produttore

Nella scheda del produttore si carica il suo modulo di brief vuoto (Word con
campi modulo). Dal progetto, «Compila nuovo brief» lo mostra come una pagina:
il gestionale riconosce testi, caselle, menu e date, precompila ciò che sa dal
progetto e scrive nel file solo i campi compilati (`ws/brief.py`). Il modulo
del produttore non fa parte del codice: resta tra i file caricati.

### Prezzi

Ogni voce di quotazione ha costo del produttore, nostri costi fissi per pezzo e
prezzo al cliente; la quotazione ha la commissione dell'agente e un margine
obiettivo, entrambi in percentuale sul prezzo di vendita. Il prezzo suggerito è
`(costo + costi fissi) / (1 − margine − commissione)`; il margine netto mostrato
toglie dal prezzo costo, costi fissi e commissione. I costi d'impianto di un
artwork nuovo entrano una sola volta nell'ordine al produttore e nella
pre-fattura.

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
- **Spedizione**: un pallet per riga (lotto, pezzi, cartoni, pesi, dimensioni,
  numero UN), da cui escono il **packing list** e la **dichiarazione
  multimodale delle merci pericolose**, compilata con i dati di pericolosità
  del prodotto (UN, denominazione, classe, EmS, quantità limitata, imballi) e
  con contatto d'emergenza e dichiarante di «Dati azienda». La dichiarazione
  ha valore legale: va sempre controllata da chi la firma.
- **Lingua**: ogni cliente ha la lingua dei documenti (italiano o inglese);
  offerta, conferma d'ordine, DDT e pre-fattura escono in quella lingua, con
  HS code e dicitura per le quantità limitate nelle note.
- **PDF su carta intestata** per offerta, conferma d'ordine, ordine al
  produttore, DDT e pre-fattura: logo e piè di pagina si impostano in «Dati
  azienda».
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

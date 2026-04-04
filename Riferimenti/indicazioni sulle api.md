# API gratuite per prezzi in tempo reale di crypto, valute e altri asset

## Executive summary

Esistono numerose API pubbliche (spesso con piano gratuito) che forniscono prezzi in tempo (quasi) reale per criptovalute, valute forex e strumenti azionari/indici, ma con differenze importanti su latenza, limiti di utilizzo, copertura degli asset e licenze d’uso.[1][2][3][4][5][6][7][8]
In generale le fonti più affidabili sono: gli exchange diretti (es. Binance) per dati di esecuzione sul singolo mercato, e i grandi aggregatori multi‑exchange (CoinGecko, CoinMarketCap, CryptoCompare, DIA, ecc.) per avere copertura ampia con controlli di qualità e storici strutturati.[7][9][10][11][1]

## Criteri di scelta e architettura dati

Quando si progettano automazioni di trading è utile distinguere tre categorie di API:

- **API di exchange singolo**: dati direttamente dalla venue dove poi mandi gli ordini (es. Binance Spot/US), con latenza minima e nessuna ambiguità sul prezzo, ma copertura limitata agli asset quotati su quell’exchange.[12][13][14]
- **API di aggregatori crypto**: raccolgono dati da molti exchange, normalizzano simboli, calcolano prezzi medi/volume‑pesati e forniscono storici, oltre a metadati, categorie, ecc.[9][10][11][7]
- **API multi‑asset (stocks/FX/crypto)**: permettono di integrare nello stesso sistema dati di azioni, indici, FX e spesso anche crypto, comode per strategie cross‑asset ma con limiti più stringenti sui piani free.[2][6][8]

Dal punto di vista tecnico avrai tipicamente:

- **REST/HTTP** per richieste puntuali (polling), più semplice da integrare ma con rischio di overshooting dei rate‑limit.
- **WebSocket/stream** per feed continuo a bassa latenza (dove disponibile), preferibile per trading sistematico rispetto a un semplice dashboard.[15][5]

## Principali API crypto “aggregator”

### CoinGecko API

CoinGecko è uno dei più grandi aggregatori indipendenti di dati crypto, integrato con oltre 1.000 exchange e più di 18.000 coin in 600+ categorie.[11]
L’API offre prezzi, market data, metadati, storici OHLCV, dati su NFT, DEX, treasury e molto altro tramite endpoint REST JSON, con piani free/pro e un nuovo piano Demo gratuito basato su API key (deprecando la vecchia API senza chiave).[16][17][9][11]

Funzionalità chiave:

- Endpoint come `/simple/price` per prezzi correnti di più coin in varie valute.[9]
- “Coins markets” per liste ordinate per market cap, volumi, ecc.[9]
- Storici, categorie, exchange list, dati on‑chain su 250+ blockchain e 1.800+ DEX.[11]

### CoinMarketCap API

CoinMarketCap fornisce un’API standard con prezzi live, market cap e dati storici OHLCV per un ampio universo di criptovalute ed exchange.[7]
Il piano free consente accesso limitato al numero di richieste e di endpoint, mentre i piani superiori estendono limiti e copertura.[7]

Dati disponibili:

- Prezzi correnti, capitalizzazione e volumi 24h per singole coin o liste.[7]
- Storici OHLCV per analisi di lungo periodo.[7]
- Dati su exchange, derivati, indici, ecc. (a seconda del piano).[7]

### CryptoCompare API

CryptoCompare è un altro grande provider di dati crypto che fornisce prezzi live, storici (minute/hour/day), info su exchange, liste di coin, social stats e news.[10][18][19]
L’API richiede una API key anche sul piano gratuito e offre endpoint per prezzi correnti, storici e metadati; i piani superiori aumentano i rate‑limit e aggiungono dataset.[18][19][10]

Endpoint tipici:

- `/data/price` e `/data/pricemulti` per prezzi attuali di una o più crypto in una o più valute.[10][18]
- `/data/histoday`, `/data/histohour`, `/data/histominute` per storici OHLCV con granularità diversa.[18][10]
- Endpoint per social data e news su specifiche coin.[18]

### DIA free crypto API

DIA offre una free crypto price API con dati in tempo reale per oltre 3.000 token, provenienti direttamente da più di 100 exchange centralizzati e decentralizzati.[1]
L’API è accessibile via REST e GraphQL, non richiede API key sul tier gratuito e include sia prezzi sia dati storici, con trasparenza completa sulle singole trade che compongono ogni prezzo.[1]

Caratteristiche rilevanti:

- Niente registrazione per iniziare, ma con rate‑limit sul piano free.[1]
- Endpoint per prezzo per address on‑chain e per vari tipi di asset.[1]
- Possibilità di migrare a soluzioni oracle on‑chain per usi DeFi.[1]

### FreeCryptoAPI

FreeCryptoAPI fornisce una “ultimate free crypto API” con prezzi in tempo reale, storici, conversioni e una serie di indicatori tecnici (RSI, MACD, segnali) e metriche di performance e volatilità.[20]
Il piano free dichiara fino a 10.000.000 richieste al mese, con dati su top 200 coin live, prezzi in varie valute locali, performance 1–720 giorni, breakout, livelli di supporto/resistenza e indicatori avanzati come bande di Bollinger e MA ribbon.[20]

### Adesic free Crypto APIs

Adesic espone API gratuite di mercato crypto con dati in tempo reale e storici su oltre 100.000 asset e 100+ exchange.[21]
Offre REST API per prezzi, volumi e liquidità, oltre a storici dettagliati (trade, aggregati) e un Transaction API per convertire crypto↔fiat e movimentare fondi.[21]

## API crypto da singolo exchange (esempio Binance)

### Binance Spot / Binance.US

Binance fornisce API REST pubbliche per dati di mercato (prezzi, ticker, order book, trades) e WebSocket per stream in tempo reale, oltre a endpoint autenticati per ordini e account.[22][13][14][12]
Per i soli dati di mercato esiste un endpoint “market data only” dedicato (`https://data-api.binance.vision`) per ridurre carico e latenza, mentre gli endpoint standard come `/api/v3/ticker/price` e `/api/v3/avgPrice` forniscono rispettivamente l’ultimo prezzo per simbolo e il prezzo medio corrente.[13][12][22]

Binance.US offre API simili per il mercato regolamentato USA, con accesso via REST e WebSocket a dati di mercato, ordini e wallet.[14]

Per un bot che esegue realmente su Binance, usare i feed Binance (REST+WebSocket) come sorgente primaria di prezzo riduce problemi di discrepanza fra dati e execution.[12][22][13][14]

## API per Forex e valute fiat

### ForexRateAPI

ForexRateAPI fornisce un’API REST JSON per tassi di cambio live e storici su oltre 150 valute, con un piano gratuito pensato per applicazioni di piccola scala.[3]
I dati provengono da una combinazione di fonti commerciali e banche globali; un algoritmo proprietario analizza i feed in tempo reale per individuare e correggere valori errati, con l’obiettivo di offrire tassi precisi e affidabili.[3]

### ExchangeRatesAPI.io

ExchangeRatesAPI.io fornisce tassi di cambio per oltre 170 valute, aggiornati fino ogni 60 secondi sui piani a pagamento.[4]
Il piano gratuito offre comunque dati “real‑time” aggiornati a intervalli regolari, sufficienti per molte applicazioni non HFT.[4]

### ExchangeRate‑API

ExchangeRate‑API espone un servizio di currency conversion per 165 valute con eccellente uptime e supporto da oltre 15 anni.[23]
Il piano gratuito aggiorna i tassi una volta ogni 24 ore, mentre i piani a pagamento hanno aggiornamenti orari, quindi va bene per strategie lente o funzionalità di conversione, ma non per trading intraday con esigenze di latenza stretta.[23]

### EODHD Forex API

EOD Historical Data (EODHD) offre una Forex API con dati in tempo reale per circa 1.100 coppie di valute via WebSocket, con latenza dichiarata intorno a 50 ms.[5]
Gli stessi tassi sono disponibili anche come “live delayed” (1 minuto di ritardo) in formato JSON/CSV, con opzioni di accesso gratuite adatte a progetti che non richiedono dati tick‑by‑tick.[5]

## API multi‑asset (stocks, FX, crypto)

### Alpha Vantage

Alpha Vantage fornisce un set di API per dati di mercato in tempo reale e storici su azioni, ETF, indici, FX, commodities e criptovalute, oltre a indicatori tecnici pre‑calcolati.[8]
I dati sono disponibili in JSON e CSV, con un piano gratuito molto popolare ma con rate‑limit piuttosto stretti, idealmente da usare come sorgente unica per sistemi non HFT o per data‑science.[8]

### Marketstack

Marketstack è una REST API per dati azionari in tempo reale, intraday e storici su oltre 30.000 ticker di varie borse globali, con 15+ anni di EOD storici e 500.000+ ticker totali.[2]
Il piano free offre 100 richieste al mese per test e piccoli progetti, mentre i piani a pagamento aumentano limite e funzionalità (inclusi EDGAR filings SEC).[2]

### StockData.org

StockData.org espone API gratuite per dati storici e intraday di azioni USA, forex e crypto, oltre a news finanziarie, con copertura di circa 150.000 ticker da 70 exchange globali.[6]
I dati sono forniti in JSON e sono pensati per essere integrati facilmente in sistemi di trading, dashboard e strumenti di analisi.[6]

### AllTick

AllTick offre una Forex Market Data API con dati in tempo reale e storici, tick‑by‑tick, order book depth e candlestick per forex, commodities, stocks, crypto e indici.[15]
Il piano “free” consente 10 simboli demo, 10 chiamate/minuto e 1 WebSocket, mentre i piani superiori ampliano simboli, rate‑limit e mercati coperti.[15]

### API Ninjas (StockPrice & CryptoPrice)

API Ninjas offre diverse API finanziarie, tra cui Stock Price API e Crypto Price API.

- **Stock Price API**: restituisce il prezzo corrente e storici per azioni su tutte le principali borse mondiali e indici (es. `^DJI` per Dow Jones); sul piano free il prezzo è ritardato di 15 minuti, il real‑time è per abbonati premium.[24]
- **Crypto Price API**: fornisce prezzi live per diverse centinaia di criptovalute, con endpoint per prezzo corrente, storici e lista dei simboli disponibili (con alcune funzioni solo per piani premium).[25]

## Sintesi comparativa di alcune API chiave

| API / Provider        | Asset coperti                 | Modello gratuito                  | Tipo sorgente           | Note su affidabilità/uso |
|-----------------------|-------------------------------|-----------------------------------|-------------------------|--------------------------|
| CoinGecko             | Crypto, NFT, DEX, on‑chain    | Piano Demo con API key, limiti mensili | Aggregatore 1.000+ exchange | Ampia copertura, usata da molte app Web3[9][16][11] |
| CoinMarketCap         | Crypto                        | Piano free con limiti richieste   | Aggregatore multi‑exchange | Dati di riferimento per market cap e ranking[7] |
| CryptoCompare         | Crypto                        | Piano free con API key            | Aggregatore multi‑exchange | Ampio set di storici, social e news[10][18][19] |
| DIA                   | Crypto                        | Free, no API key (rate‑limited)   | Direct feed da 100+ CEX/DEX | Focus su trasparenza delle singole trade[1] |
| FreeCryptoAPI         | Crypto                        | Piano free con fino a 10M richieste/mese | Aggregatore (top 200 live) | Molti indicatori tecnici e metriche pronte all’uso[20] |
| Adesic                | Crypto                        | API gratuite per dati di mercato  | Aggregatore 100+ exchange | Copertura molto ampia + Transaction API per pagamenti[21] |
| Binance (Spot/US)     | Crypto listate su Binance     | Market data pubblici, chiave non sempre richiesta | Exchange singolo         | Migliore per trading su Binance, bassa latenza[12][22][13][14] |
| ForexRateAPI          | FX                            | Piano free, REST JSON             | Aggregato da banche/fonti commerciali | Algoritmi di correzione errori in real‑time[3] |
| ExchangeRatesAPI.io   | FX                            | Piano free con aggiornamenti regolari | Aggregatore FX            | Aggiornamenti fino a ogni 60s sui piani pro[4] |
| ExchangeRate‑API      | FX                            | Piano free (aggiornamento giornaliero) | Aggregatore FX            | Storico servizio con alta affidabilità operativa[23] |
| EODHD Forex API       | FX                            | Accesso live delayed free         | Aggregatore FX            | WebSocket real‑time a ~50 ms su piani premium[5] |
| Alpha Vantage         | Stocks, FX, crypto, indicatori | Piano free con rate‑limit stretti | Aggregatore multi‑asset  | Centrale per progetti retail/quant non HFT[8] |
| Marketstack           | Stocks                        | 100 richieste/mese free           | Aggregatore borse globali | Copertura globale e 15+ anni di storici[2] |
| StockData.org         | Stocks, FX, crypto, news      | Piano free                        | Aggregatore multi‑asset  | 150k+ ticker su 70 exchange[6] |
| AllTick               | Stocks, FX, crypto, commodities, indici | Piano free limitato a 10 simboli | Aggregatore multi‑asset  | Tick‑by‑tick + order book, utile per backtest e low‑latency[15] |
| API Ninjas            | Stocks, crypto                | Piano free con limitazioni        | Aggregatore multi‑asset  | Stock price free ritardato 15 minuti; crypto live[24][25] |

## Considerazioni su affidabilità e licenze d’uso

- **Affidabilità come fonte dati**: gli exchange diretti (es. Binance) sono la fonte “ground truth” per il loro order book, ma gli aggregatori come CoinGecko, CoinMarketCap e CryptoCompare sono più robusti per view multi‑exchange, con controlli di qualità e normalizzazione dei dati.[10][11][9][7]
- **Latenza**: per esecuzione su uno specifico exchange, meglio usare direttamente il WebSocket/REST di quell’exchange; gli aggregatori aggiungono un minimo di latenza ma offrono copertura più ampia e ridondanza.[13][5][12][15]
- **Licenza e attribution**: molti provider free richiedono attribution (logo, link) o vietano esplicitamente l’uso per trading ad alta frequenza o per rivendere i dati; CryptoCompare, per esempio, chiede attribution per chi usa l’API free.[19]
- **“Real‑time” vs delay**: alcuni servizi free etichettano i dati come “real‑time” ma con ritardi di 15 minuti per il piano gratuito (es. Stock Price API di API Ninjas), oppure con aggiornamenti a 24 ore (es. ExchangeRate‑API free); è cruciale leggere sempre bene la sezione “Free tier”/“Limitations”.[24][23]

## Linee guida pratiche per il tuo sistema di automazione

Per un sistema di automazione di trading crypto/FX/altro con budget zero o quasi, una strategia robusta può essere:

- Usare **API dell’exchange** per qualsiasi logica che dipende dal prezzo di esecuzione effettivo (es. trigger degli ordini, gestione risk per simboli quotati lì).[14][12][13]
- Affiancare **uno o due aggregatori crypto** per funzioni trasversali (screener, ranking, filtri su market cap/volume, categorie, analisi multi‑exchange), scegliendo in base a limiti free e feature (CoinGecko/CoinMarketCap/CryptoCompare/DIA).[11][9][10][1][7]
- Per **FX** appoggiarsi a un provider con algoritmo di aggregazione (ForexRateAPI, ExchangeRatesAPI.io, EODHD) e usare l’exchange o broker solo per l’esecuzione, se necessario.[3][4][5]
- Per **azioni/indici**, unificare feed tramite provider multi‑asset come Alpha Vantage, Marketstack o StockData.org, consapevole dei rate‑limit del piano free.[6][8][2]

In fase di design conviene prevedere un layer astratto (es. `PriceProvider` con implementazioni `ExchangePriceProvider`, `AggregatorPriceProvider`, `FXPriceProvider`) in modo da poter sostituire facilmente backend diversi se cambiano limiti, costi o requisiti di affidabilità.
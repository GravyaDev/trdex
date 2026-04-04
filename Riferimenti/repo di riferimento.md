***

## Framework completi di trading bot (multi‑exchange)

### Freqtrade (Python)

- Repo: `freqtrade/freqtrade` – free, open source crypto trading bot in Python. [freqtrade](https://www.freqtrade.io/en/stable/)
- Supporta tutti i principali exchange (via connettori), backtest, hyper‑opt, gestione rischio, controllo via Telegram/web UI; documentazione ufficiale spiega installazione, gestione API key, ecc. [freqtrade](https://www.freqtrade.io/en/stable/installation/)
- Moltissime strategie open source in repo separati (`freqtrade-strategies`) che mostrano come strutturare logica di ingresso/uscita. [github](https://github.com/nateemma/strategies)

È un ottimo riferimento per: struttura del progetto, gestione config, orchestrazione di più exchange, layer di dati e di strategia.

### Hummingbot (market making / HFT‑like)

- Repo: `hummingbot/hummingbot` – framework open source per creare e deployare bot di market making e arbitraggio su vari exchange centralizzati e DEX. [hummingbot](https://hummingbot.org/docs/)
- Hummingbot è pensato proprio per strategie ad alta frequenza su order book (market making, cross‑exchange, LP), con connettori “seri” e architettura modulare. [hummingbot](https://hummingbot.org)

È uno dei pochissimi progetti open ad avvicinarsi davvero alla logica HFT retail su crypto (in termini di struttura, non di colocation).

### Altri framework/bot multi‑exchange

- **Haehnchen/crypto-trading-bot** – bot in Node.js per Bitfinex, Bitmex, Binance, Bybit, ecc., fa heavy use di WebSocket + ccxt; è uno dei progetti più noti nella categoria “bot pubblico multi‑exchange”. [github](https://github.com/topics/ccxt)
- **joelsfoster/gizmo** – bot che riceve segnali da TradingView via webhook e usa CCXT per eseguire ordini sugli exchange; utile come esempio di integrazione segnali esterni + esecuzione via API. [github](https://github.com/joelsfoster/gizmo)

***

## Repo focalizzate su HFT / WebSocket e data feed

### Crypto HFT Data Aggregator

- Repo: `SpiralDevelopment/crypto-hft-data`. [github](https://github.com/SpiralDevelopment/crypto-hft-data)
- Scopo: **collezionare in tempo reale order book, trade e altri dati HFT** da più exchange (Binance, Bitmex, Okex, Bitfinex, Coinbase, Bitstamp, Kraken) usando WebSocket. [github](https://github.com/SpiralDevelopment/crypto-hft-data)
- Configurazione via `configs.json` dove scegli per ogni exchange quali stream (orderbook, trade, liquidation, ecc.) salvare; è un ottimo esempio di “strato dati HFT multi‑exchange” senza logica di trading. [github](https://github.com/SpiralDevelopment/crypto-hft-data)

Questo è molto vicino a quello che descrivevi: layer di raccolta dati real‑time via WS da varie venue.

### Deribit WebSocket HFT trading app

- Repo: `automatesolutions/WebSocket_HFT`. [github](https://github.com/automatesolutions/WebSocket_HFT)
- Trading app che si connette a Deribit via WebSocket, con funzioni per **piazzare, cancellare, modificare ordini**, leggere order book e posizioni; è ottimizzata per performance (async, gestione memoria, threading). [github](https://github.com/automatesolutions/WebSocket_HFT)
- Codice in C++ con moduli separati per `websocket_handler`, `trade_execution`, main loop di trading, ecc., quindi molto utile come reference per architettura “HFT‑oriented”. [github](https://github.com/automatesolutions/WebSocket_HFT)

### Dashboard HFT su Binance

- Repo: `arturogonzalezm/HFTCryptoDashboard`. [github](https://github.com/arturogonzalezm/HFTCryptoDashboard)
- Applicazione in Go per **streaming real‑time di dati crypto** da Binance via WebSocket, con focus su scenari HFT. [github](https://github.com/arturogonzalezm/HFTCryptoDashboard)
- Ha strutture separate per config, client WS, gestione segnali di shutdown, logging, ecc. – buon esempio di “client WS robusto” per Binance. [github](https://github.com/arturogonzalezm/HFTCryptoDashboard)

### SDK / helper per Binance WebSocket

- Repo: `oliver-zehentleitner/unicorn-binance-websocket-api`. [github](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api)
- SDK Python che ti permette con poche righe di creare connessioni WebSocket multiple/multiplexate a Binance (trade, kline, ticker, depth, bookTicker, ecc.) e anche inviare ordini via WS. [github](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api)
- Gestisce reconnection, code, parsing, ecc.; perfetto se vuoi concentrarti sulla logica di trading invece che sulla plumbing del WebSocket. [github](https://github.com/oliver-zehentleitner/unicorn-binance-websocket-api)

### Semplici bot WS su Binance

- Repo: `vanillaiice/gocryptobot` – semplice trading bot in Go che usa Binance Spot + WebSocket API per comprare/vendere a margini specificati dall’utente; include config YAML e usa server testnet Binance. [github](https://github.com/vanillaiice/gocryptobot)
- Repo: `KevinMcK100/binance-bot-websocket` – micro‑servizio WS che monitora i trade di un altro bot su Binance futures e triggera callback (es. spostare stop loss dopo take profit). [github](https://github.com/KevinMcK100/binance-bot-websocket)

### Utility per order book multi‑exchange

- Repo: `Marfusios/crypto-websocket-extensions` – libreria che aggiunge un **order book unificato** e altre estensioni ai client WS di vari exchange; include data structure efficiente per L2/L3 e gestione snapshot+delta. [github](https://github.com/Marfusios/crypto-websocket-extensions)

Questo è molto utile se vuoi implementare tu una logica HFT (market making, arbitraggio) con order book unificato tra exchange.

***

## Librerie base per collegarsi alle API (building blocks)

### CCXT (REST + WebSocket, multi‑exchange)

- Repo: `ccxt/ccxt` – libreria in JS/TS/Python/PHP/C#/Go che supporta 100+ exchange, con API pubbliche e private uniformate. [pypi](https://pypi.org/project/ccxt-robotter/)
- Fornisce accesso rapido ai dati di mercato e alle operazioni di trading, con CLI integrata per scripting e automazioni di base (es. `ccxt binance fetchTicker BTC/USDT`, `watchTrades` in streaming). [github](https://github.com/ccxt/ccxt/wiki/CLI)

È il mattoncino standard se vuoi scriverti da zero il tuo framework multi‑exchange.

***

## Raccolte “awesome” per esplorare altri repo

Se vuoi esplorare altre soluzioni simili:

- **botcrypto-io/awesome-crypto-trading-bots** – lista curata di bot, librerie e market‑data client (inclusi progetti come `crypto-trading-bot`, `CryptoSignal`, vari client WS per Binance/Kraken/KuCoin, ecc.). [github](https://github.com/botcrypto-io/awesome-crypto-trading-bots)
- **hummingbot/awesome-hummingbot** – raccolta di strumenti, tutorial e risorse legate all’ecosistema Hummingbot (strategie, demo, integrazioni DEX, ecc.). [github](https://github.com/hummingbot/awesome-hummingbot)

***
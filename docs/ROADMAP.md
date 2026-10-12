# Roadmap trdex

Aggiornata al 2026-10-12. Questo file è la fonte unica per sapere cosa c'è da fare e in che ordine; `Task Board.md` rimanda qui.

**Regola**: chi chiude una voce aggiorna questo file nella stessa PR. Lo stato, le decisioni e i limiti noti stanno qui, non nella memoria di chi ci ha lavorato.

---

## 1. PR aperte e ordine di merge

| Ordine | PR | Contenuto | Base |
|---|---|---|---|
| 1 | #14 | Unificazione main + llm-agents in un'unica app agent-driven. Contiene già #4–#9 e #11–#13. | `main` |
| 2 | #15 | Regime refresher settimanale (ricalcola e rivalida) e notifiche Telegram + email instradabili per tipo di evento | `unify/agent-driven` |
| 3 | #16 | Salute dei feed in `/v1/status` e nella dashboard; gate macro (niente ingressi a ridosso di FOMC/CPI/NFP) | #15 |
| 4 | #17 | Budget di rischio di portafoglio (riduce prima di rifiutare), tetto per cluster correlati, rendimento/rischio minimo | #16 |
| 5 | #18 | Short e leva: perpetual Binance USDⓈ-M, margine isolato, gate di liquidazione, funding, replay nel backtest | #17 |
| poi | #10 | Baseline CI: va rigenerata dopo i merge sopra | `main` |
| poi | #3 | Dependabot: dopo #10 | `main` |

- Si fa il merge nell'ordine indicato. Dopo il merge di #14, le PR #4–#9 e #11–#13 risultano già incluse e si chiudono.
- Se GitHub non sposta da solo la base di una PR impilata quando la sua base viene mergiata, la si cambia a mano in `main`.
- Dopo il merge vanno configurati i canali di notifica (bot Telegram, SMTP). Le istruzioni sono in README → Notifications; la scelta del canale per ogni evento si fa dalla dashboard.

## 2. Decisioni prese

- **Un'unica app agent-driven.** main e llm-agents non sono più due linee separate.
- **Niente dipende dalla memoria dell'operatore.** Ogni passo periodico è un job interno con notifica (regime refresher, calendario macro, readiness). All'operatore non si lasciano compiti ricorrenti.
- **Bounds di regime.** Ogni settimana il refresher ricalcola e rivalida; scrive i nuovi bounds solo se la validazione passa. Se non passa, i vecchi bounds scadono e il live si ferma, con notifica.
- **News e sentiment.** Si usano le fonti già presenti: news CryptoCompare/StockData e canali Telegram di news indicizzati in Qdrant. Niente X/Reddit.
- **Short e leva: sì.**
  - Venue live: **Binance USDⓈ-M perpetual**.
  - Leva massima di default **3x**, margine **isolato**, modificabile dalla dashboard.
  - Si fanno **prima** della conferma d'ingresso (voce B).

## 3. Prossimi lavori, in ordine

### A. Short e leva — fatto, PR #18 (da mergiare dopo #17)

Branch `feat/shorts-leverage`, impilato su #17. Dettagli in `docs/superpowers/plans/2026-10-11-shorts-leverage.md` e nel README (Shorts and leverage).

Criteri di accettazione:

- **Analyst**
  - Abilita `OPEN_SHORT` e `CLOSE_SHORT`, oggi vocabolario riservato.
  - Il fallback a regole è speculare al long. Prompt LLM aggiornato.
- **Risk node**
  - Stop e target per lato: per uno short lo stop sta sopra l'ingresso.
  - Tetto di leva `max_leverage` (default 3).
  - **Gate di liquidazione**: con margine isolato lo stop deve scattare con ampio margine prima del prezzo di liquidazione, altrimenti l'ingresso è rifiutato.
  - Il limite per cluster conta le posizioni **nella stessa direzione**: un long BTC e uno short ETH si coprono.
  - Budget di rischio e sizing non cambiano: la perdita allo stop non dipende dalla leva, che riduce solo il margine impegnato.
- **Esecuzione**
  - Gateway Binance USDⓈ-M via ccxt, con lo stesso rate limiting degli altri percorsi ccxt.
  - Margine isolato; leva impostata per simbolo prima dell'ordine; uscite reduce-only.
- **Simulatore**
  - Short, margine, funding ogni 8h e liquidazione.
- **Portafoglio e contabilità**
  - Posizioni SELL tracciate, con P&L di segno corretto.
  - Margine impegnato = nozionale / leva.
  - L'equity non cambia con la leva.
- **StopLossMonitor**: trigger per lato (verificare e completare).
- **Telegram**
  - I segnali SELL aprono short, con gli stessi gate dei long.
  - Si toglie il rifiuto "long-only" allo step 0b dell'executor.
- **Backtest e refresher**
  - Il motore gestisce già gli short; si aggiungono costo di funding, leva e check di liquidazione.
  - `LiveRuleEngine` emette short; il refresher rivalida long e short insieme.
- **Dashboard**
  - Impostazione della leva.
  - Per ogni posizione: lato, margine e prezzo di liquidazione.
- **Go-live**: gli short devono superare la stessa rivalidazione dei long prima del live.

### B. Conferma d'ingresso e scheda decisione

- **ENTER / WAIT / SKIP.** Quando l'Analyst dice OPEN, l'ingresso resta *pending*.
  - Lo conferma la chiusura della barra 1h successiva oltre il livello del segnale (sopra per un long, sotto per uno short), con volume sopra la media a 20 barre.
  - Se la conferma non arriva entro N barre (default 3), l'ingresso viene scartato (SKIP).
  - La regola va riprodotta in `LiveRuleEngine` e nel backtest.
- **News "watch"**: una news classificata come "da osservare" sul simbolo porta a WAIT invece di ENTER.
- **Completezza**: se manca un input essenziale (prezzo, candele, CV di regime, calendario macro in live), la decisione è HOLD con il motivo.
- **Protezioni** (da Freqtrade): gate deterministici nel Risk node, riprodotti nel backtest.
  - Cooldown per simbolo dopo uno stop-loss: niente nuovo ingresso su quel simbolo per N ore.
  - Pausa globale dopo N stop in X ore (StoplossGuard).
- **Time-stop, da testare**: chiusura di una posizione ferma da N ore senza progressi (idea del TrendRider). Si adotta solo se il backtest del refresher migliora.
- **Dashboard**
  - Scheda decisione per ciclo: Scout → News → Analyst → Risk → Executor, con esito e motivi.
  - Tile KPI di rischio: rischio per posizione, rischio di portafoglio, max drawdown, VaR 95%, esposizione.
  - **Rapporto settimanale** allegato alla notifica del refresher, con le metriche dei tearsheet tipo quantstats/pyfolio calcolate in casa, senza nuove dipendenze:
    - Sortino, Calmar, VaR/CVaR 95%;
    - rendimenti mensili, Sharpe mobile;
    - risultati separati per long/short e per fonte (agente, Telegram, manuale).
  - Barra di stato della pipeline.

### C. Edge misurato: finestre temporali, Kelly frazionario, stime bayesiane

Origine: post "framework dato a Claude" (video seb.ai, 2026-10-11). Delle sue 4 regole, il filtro di volatilità c'è già (gate 4c). Restano queste tre.

- **Stime bayesiane**
  - Win rate e payoff medio con posteriori Beta per segmento: strategia × lato × simbolo, e per fonte Telegram.
  - Aggiornate a ogni chiusura.
  - Con pochi trade la stima resta vicina al prior, quindi niente conclusioni su 3 operazioni.
  - Sostituiscono le soglie fisse dell'affidabilità Telegram (`reliability_min_samples`, `reliability_win_rate_min`) con un limite inferiore credibile.
- **Kelly frazionario**
  - Calcolato sulle stime bayesiane: `f* = (p·b − q)/b`, applicato a ¼.
  - Usato solo come **tetto**: riduce il rischio per trade quando l'edge misurato cala, ferma un segmento con edge ≤ 0, e non supera mai `risk_per_trade_pct`.
  - Non usa la "confidenza" dell'LLM, che non è una probabilità calibrata.
- **Finestre temporali**
  - `scripts/backtest/seasonality.py` gira in automatico nel refresher settimanale.
  - Una finestra ora/giorno diventa gate solo se supera, insieme:
    - la correzione Holm/BH;
    - la stabilità tra sotto-periodi;
    - l'holdout;
    - la rivalidazione del backtest con il filtro attivo.
  - Il conteggio dei test cresce a ogni run, così ripetere l'analisi ogni settimana non produce falsi edge per caso.
  - Se nessuna finestra passa, non si applica nessun filtro.
- **Validazione più severa nel refresher** (López de Prado, *Advances in Financial ML*; strumenti come Lacuna):
  - **Deflated Sharpe Ratio** come criterio, al posto dello Sharpe grezzo. Tiene conto di quante varianti sono state provate nel tempo (lo stesso contatore dei test delle finestre temporali) e di asimmetria e curtosi dei rendimenti.
  - **Walk-forward**: i bounds e le regole devono reggere su finestre successive, non solo sull'intero periodo.
  - **Monte Carlo sull'ordine dei trade** per la distribuzione del max drawdown; il criterio usa il 95° percentile, non il valore singolo.
- **Esponente di Hurst come candidato filtro di regime**: la strategia RSI/SMA segue il trend, quindi H > 0,5 dovrebbe aiutarla. Si adotta solo se la rivalidazione migliora.

### D. Frontend grafici con lightweight-charts

- Candele per simbolo con ingressi, uscite e linee di stop/target, servite dall'API.
- **Grafico del trade nella notifica**: alla chiusura di una posizione, un PNG con candele, ingresso, uscita e stop (mplfinance) allegato al messaggio Telegram/email.
- La dashboard Streamlit resta finché il nuovo frontend non è alla pari.

### E. Manutenzione

- #10: rigenerare la baseline CI dopo i merge.
- `tests/test_audit_fixes.py`: 29 errori preesistenti dovuti a percorsi Windows assoluti (`c:/Users/...`). Vanno resi relativi al repo.
- Rotazione delle credenziali Telegram al go-live (vedi `Task Board.md`).

### F. Dati dei derivati Binance (via ccxt, già rate-limited)

Origine: awesome-systematic-trading (2026-10-12), in particolare FundingRadar, ByKaranteli e 0xArchive come esempi. I dati però si prendono da Binance stesso.

- **Funding storico reale**: sostituisce il tasso fisso `funding_rate_8h` nel backtest e in simulazione. Chiude un limite noto di #18.
- **Open interest, rapporto long/short e liquidazioni**:
  - Come input per Scout/Analyst, a indicare l'affollamento del mercato.
  - Come filtri candidati, ad esempio niente long con funding molto alto. Un filtro si adotta solo se migliora la rivalidazione.

### G. Validare le decisioni dell'LLM

Origine: TraderHarness. Oggi la validazione copre solo il fallback a regole, perché l'LLM "conosce" la storia e un suo replay sarebbe contaminato.

- **Replay a campione su dati anonimizzati**: simbolo e date nascosti, prezzi normalizzati.
- **Obiettivo**: stimare l'edge dell'Analyst LLM rispetto alle regole.
- **Costo**: budget fisso per run.
- **Uso del risultato**: decide se l'LLM resta il decisore principale o diventa solo annotazione.

### Ordine consigliato

B → F → C → G → D, con E in parallelo quando serve.

### Scartati dalla stessa lista (fuori dal perimetro di trdex)

- Mercati predittivi (Polymarket, Kalshi).
- Arbitraggio, market making e funding carry spot/perp. Il carry è una classe di strategia diversa e oggi è bloccato di proposito dalla guardia sui lati opposti.
- Sostituire il motore con framework esterni (nautilus_trader, freqtrade, jesse): il nostro motore rigioca il live 1:1.
- Vendor di dati a pagamento o via MCP/x402.
- Framework RL/ML (FinRL e simili).
- Ottimizzatori di portafoglio (HRP, Black-Litterman): con un rischio per trade dello 0,1% e il tetto per cluster non servono.

## 4. Limiti noti

- Il gate macro non è riprodotto nel backtest. Lo storico si accumula in `macro_events`, quindi un replay sarà possibile più avanti.
- I cluster correlati sono calcolati sugli ultimi 90 giorni e applicati a tutta la finestra del backtest: un leggero look-ahead.
- Nel backtest l'equity è cassa più nozionale impegnato e ignora il P&L non realizzato.
- Le decisioni LLM non si possono rigiocare sullo storico: la validazione copre il fallback a regole.

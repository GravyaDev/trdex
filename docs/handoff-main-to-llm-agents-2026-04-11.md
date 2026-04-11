# Handoff: main → llm-agents — 2026-04-11

**Audience**: chiunque lavora sul worktree sister `trdex-llm/` (branch
`llm-agents`). Questo documento riassume le modifiche su `main` che
non sono ancora nel branch, così il merge forward (`git merge
origin/main` dentro `trdex-llm/`) parte con il contesto giusto e le
possibili aree di conflitto già identificate.

**Generato da**: sessione trdex main del 2026-04-11, dopo il push di
tutti i commit elencati sotto.

**Workflow ufficiale** (da `.claude/memory.md`):
> I bug di production scoperti su `main` vanno fixati qui, poi merged
> forward nel branch (`cd ../trdex-llm && git merge origin/main`).
> MAI il contrario.

---

## Commit da mergere (ordine cronologico, 9 commit)

| # | SHA | Titolo | Aree toccate |
|---|-----|--------|--------------|
| 1 | `bd3e8bf` | fix(feeds): reject stale tickers + swap delisted RNDR/MATIC for RENDER/POL | `market/feeds/binance.py`, `config.py`, `docker-compose.yaml`, tests |
| 2 | `496b4d1` | tune(gate): simulation days 30 → 25 | `config.py` |
| 3 | `9fe0b63` | fix(compose): TRDEX_GATE_MIN_DAYS default 30 → 25 | `docker-compose.yaml` |
| 4 | `bd4fb70` | feat(telegram): Step 1 observe-only signal tracking | migration 011, `telegram/tracker.py`, `telegram/evaluator.py` (new), `api/app.py`, `dashboard/app.py`, `storage/signal_outcome_models.py`, `storage/signal_outcome_repo.py`, `services/runtime_config.py` |
| 5 | `47c0531` | feat(status): expose telegram signals_tracked and evaluator_running | `api/app.py` |
| 6 | `fbcc9e6` | feat(telegram): numeric chat_id support + discovery scripts | `telegram/monitor.py`, `scripts/telegram_list_channels.py` (new), `scripts/telegram_join_channel.py` (new) |
| 7 | `efefabb` | feat(security): encrypt runtime_config credentials at rest (Fernet) | `services/credentials_crypto.py` (new), `services/runtime_config.py`, `config.py`, tests |
| 8 | `d5372f9` | fix(compose): wire TRDEX_CONFIG_ENCRYPTION_KEY | `docker-compose.yaml`, `.env.example`, `tests/test_audit_fixes.py` |
| 9 | `ada5930` | feat(risk): persistent stop-loss event log | migration 013, `storage/stop_loss_event_models.py` (new), `storage/stop_loss_event_repo.py` (new), `risk/stop_loss.py`, `Task Board.md`, tests |

---

## Per commit: cosa cambia e perché

### 1. `bd3e8bf` — StaleTickerError + delisted symbol swap

**Incidente**: Binance ha delistato RNDR e MATIC il 2026-03-24.
CCXT continuava a restituire il last-traded price come "live ticker"
senza errore → entry via feed aggregato + exit via Binance-pinned
→ prezzi incoerenti → **+$1721 di phantom gain su 19 trade in DB**.

**Fix**:
- `BinanceFeed.get_ticker()` ora solleva `StaleTickerError` se
  `now - ticker.timestamp > 5 minuti`. Threshold codificato.
- Simboli default nel compose: RNDR → RENDER, MATIC → POL.
- 3 test unit di freshness in `tests/market/test_binance_freshness.py`.

**Rilevanza per llm-agents**: il branch usa lo stesso `BinanceFeed`.
Nessuna nuova interfaccia — aggiunge solo una eccezione che il
chiamante dovrebbe già gestire via `try/except FeedError`. Basso
rischio di conflitto.

### 2 + 3. Gate min days 30 → 25

**Motivo**: dopo il nuclear DB reset del 2026-04-11, abbiamo voluto
accorciare il tempo di simulazione richiesto dal readiness gate per
arrivare al live mode. Due commit perché il primo fixa solo la
default Python (`config.py`), il secondo il compose override che
aveva la propria default `${VAR:-30}` che vinceva sulla Python.

**Rilevanza per llm-agents**: il branch eredita la stessa gate
config via `settings.gate_min_days`. Zero cambio di API, solo un
numero più basso. Se il branch ha modificato `config.py` per
aggiungere campi LLM (temperature, max_tokens, per agent) attenzione
al merge conflict su quella stessa sezione — **area di attenzione**.

### 4. `bd4fb70` — Telegram Step 1 observe-only (commit grosso)

**Obiettivo**: integrare i segnali di trading di Matteo Zanni
(Telegram) come fonte osservazionale, senza toccare capitale.

**Cambi di schema**:
- Migration 011 rende `signal_outcomes.exit_price` nullable e
  `budget` default 0. Permette di persistere segnali prima che
  abbiano un outcome.

**Data model**:
- `SignalOutcome.exit_price: Decimal | None`, nuova property
  `is_open`, `pnl`/`pnl_pct` ritornano 0 per segnali aperti.
- `SourceStats` ora ha `open_signals` e `closed_signals` separati;
  `win_rate` è calcolato solo su closed_signals.

**Persistence**:
- `SignalOutcomeRepository.save()` accetta `exit_price=None`.
- Nuovi metodi `open_outcomes()` e `close_outcome()`.

**Streaming**:
- `_telegram_background()` in `api/app.py` persiste ogni signal
  con `exit_price=None`, `budget=0`, `note=json(targets, stop_loss)`.

**Nuovo modulo `telegram/evaluator.py`**:
- `score_signal()`: pura, walk cronologico OHLCV, first-touch
  resolution (tp/sl/stale/open). Ambiguous bar → SL (conservativa
  per scalping tight-TP).
- `evaluator_loop()`: asyncio task schedulato ogni 3600s.
- Timeframe auto-selezionato dall'età del segnale (5m ≤6h, 15m
  ≤24h, 1h older). Signal >24h senza resolution → stale.

**API**:
- `/v1/signals` restituisce ora `{report: [...], recent: [last 50]}`
  con win_rate, roi_pct, per-signal status.

**Dashboard**:
- Nuovo expander "🟣 Telegram Signals (observe-only)" con 4 metric
  card, tabella per-source, tabella recent.

**Runtime config**:
- Aggiunto `scheduler/telegram_eval_interval` al registry (int).

**Rilevanza per llm-agents**: **alta priorità di review**.
- `api/app.py` è toccato pesantemente in tutte e due le branch —
  conflitto quasi certo sul lifespan. **Risolvere preservando sia
  il `_telegram_eval_task` creato qui, sia qualunque task LLM
  il branch abbia introdotto**.
- `dashboard/app.py` ha un expander nuovo — conflitto possibile se
  il branch ha cambiato la stessa area.
- `services/runtime_config.py` ha `telegram_eval_interval` nel
  registry: se il branch ha aggiunto le sue chiavi LLM-related,
  **mergere entrambe le liste** in `_KEY_REGISTRY`.

### 5. `47c0531` — `/v1/status` extended

**Aggiunte**: `telegram.signals_tracked` (count dal tracker
in-memory) + `telegram.evaluator_running` (bool del task).

**Rilevanza**: patch chirurgica in `/v1/status`, il branch quasi
certamente non la tocca lì. Nessun conflitto atteso.

### 6. `fbcc9e6` — Channel discovery + numeric chat_id

**Motivo**: i canali privati di Telegram non hanno @username, serve
un chat_id numerico negativo. Telethon non lo coerces da stringa.

**Cambi**:
- `TelegramMonitor._normalize_channels()`: stringhe digit-only
  (con segno) → `int`, username → `str`. Applicato a stream() e
  fetch_recent().
- `scripts/telegram_list_channels.py`: iter_dialogs con output
  tabellare per scoprire chat_id.
- `scripts/telegram_join_channel.py`: join via t.me/+hash invite
  link (per canali privati con link libero).

**Rilevanza**: `telegram/monitor.py` può avere conflict se il
branch ha modificato la classe. Review il diff di monitor.py.

### 7. `efefabb` — Security HIGH: encrypted credentials

**Vulnerabilità**: runtime_config.credentials contiene API keys in
plaintext. Qualsiasi accesso read al DB (backup, debug endpoint,
SQL tooling) esfiltra `telegram_api_hash`, `binance_api_secret`,
`perplexity_api_key`, ecc.

**Fix**:
- Nuovo modulo `services/credentials_crypto.py` con wrapper Fernet
  (AES-128-CBC + HMAC-SHA256 + IV random) dalla libreria
  `cryptography` (dipendenza transitive già presente).
- Master key da env var `TRDEX_CONFIG_ENCRYPTION_KEY` (44-char
  urlsafe base64). Unset = passthrough mode + WARNING log, così
  dev/CI funzionano out-of-the-box.
- Ciphertext identificato dal Fernet version marker `gAAAAA`.
- `python -m trdex.services.credentials_crypto` genera una nuova key.
- Wrong-key decrypt ritorna il ciphertext originale con ERROR log
  — la riga non viene mai silenziosamente corrotta.

**Service wiring**:
- `RuntimeConfigService.load()` decripta credentials al load.
- `put()` / `put_category()` / `seed_from_settings()` criptano i
  valori credentials prima del write.
- Solo la category `credentials` è criptata (thresholds, symbols,
  scheduler, feeds restano plaintext).
- `migrate_plaintext_credentials()`: one-shot idempotente che
  riscrive legacy plaintext rows come ciphertext al boot. No-op
  quando cipher è disabilitato.
- `init_config_service()` sequence: init_cipher → load → migrate
  → reload → seed.

**Test**: 13 nuovi (`tests/test_credentials_crypto.py`) — passthrough,
round-trip, empty-value handling, malformed key fallback, wrong-key
decrypt safety, service integration con fake repo monkeypatch.

**Rilevanza per llm-agents**: il branch eredita il servizio
runtime_config. Se ha aggiunto chiavi LLM nella category credentials
(es. `openai_api_key`, `anthropic_api_key`, `google_api_key`), quelle
vengono automaticamente criptate senza cambi ulteriori. **Nessuna
azione richiesta oltre al merge**. Ma verificare: se il branch ha
toccato `seed_from_settings()` o `put()` per la sua logica LLM,
conflitto certo — rebase preservando l'encryption path.

### 8. `d5372f9` — compose wiring encryption key

**Cosa**: aggiunta la riga
`TRDEX_CONFIG_ENCRYPTION_KEY: '${TRDEX_CONFIG_ENCRYPTION_KEY:-}'`
al blocco `environment:` del servizio app, documentazione in
`.env.example`, test `REQUIRED_VARS` esteso.

**Rilevanza**: cambi chirurgici al compose, conflict solo se il
branch ha già aggiunto sue env var in quella zona. Facile da
risolvere manualmente.

### 9. `ada5930` — Persistent stop-loss event log

**Debt**: `StopLossMonitor._events` era una `list[StopLossEvent]`
Python in-memory. Ogni restart del container cancellava tutta la
storia — proprio quando ti serviva di più per fare incident review.

**Fix**:
- Migration 013 crea `stop_loss_events` (idempotente, 2 indici:
  fired_at DESC e reason).
- ORM model `StopLossEventRecord`.
- Nuovo `StopLossEventRepository` con `save / recent / count`.
- `StopLossMonitor.start()` chiama `_hydrate_events_from_db()` che
  carica gli ultimi 50 rows nel cache in-memory e seeda il counter
  cumulativo da `repo.count()`. Swallows DB errors.
- `check_now()` chiama `_persist_event()` per ogni nuovo evento —
  best-effort, per-event try/except, **mai blocca il risk path**.
- Cache bounded a max ~200, trim a 100 per evitare crescita
  illimitata.
- `status.events_fired` ora usa il counter persistente, non
  `len(self._events)` — il numero sopravvive ai restart.

**Test**: 5 nuovi (`tests/test_stop_loss_persistence.py`) — persist,
DB failure swallow, hydrate cache, hydrate DB error swallow, counter
semantics.

**Rilevanza per llm-agents**: `risk/stop_loss.py` è toccato. Se il
branch ha modificato `StopLossMonitor` per integrare LLM
risk-approval, **merge conflict quasi certo** su `__init__`, `start`,
e `check_now`. Strategia: preservare sia i nuovi campi di stato
(`_events_fired_total`, `_hydrate_events_from_db`, `_persist_event`),
sia le modifiche LLM del branch.

---

## Aree di conflitto attese (sommario)

| File | Rischio | Perché |
|---|---|---|
| `src/trdex/api/app.py` | **Alto** | Lifespan modificato pesantemente (telegram eval task, stato `_telegram_eval_task`). Il branch certamente tocca la stessa funzione per wire-up degli LLM agent |
| `src/trdex/risk/stop_loss.py` | **Alto** | StopLossMonitor esteso con persistence + hydrate. Il branch può aver aggiunto LLM risk gates |
| `src/trdex/services/runtime_config.py` | **Medio** | Registry esteso, service encryption path. Il branch può aver aggiunto chiavi LLM |
| `src/trdex/config.py` | **Medio** | Nuovo campo `config_encryption_key`. Il branch può aver aggiunto campi LLM (temperature, model per agente) |
| `src/trdex/dashboard/app.py` | **Medio** | Nuovo expander Telegram. Il branch può aver rifatto dashboard |
| `docker-compose.yaml` | **Basso** | Solo 1 nuova env var + 1 default cambiato |
| `src/trdex/telegram/monitor.py` | **Basso-Medio** | Aggiunto `_normalize_channels`. Se il branch non tocca monitor, nessun conflict |

---

## Step consigliati per il merge forward

```bash
# Dal worktree llm-agents (NON da qui)
cd c:/Users/Daniele/Antigravity/trdex-llm

# 1. Aggiornare references
git fetch origin

# 2. Verificare stato del branch
git status
git log --oneline -5

# 3. Dry run — vedere in anticipo i conflitti
git merge --no-commit --no-ff origin/main
#    Se mostra conflitti → git merge --abort e pianificare

# 4. Merge vero (se pulito)
git merge origin/main

# 5. Se conflitti: risolvere prioritizzando le aree del risk path
#    (stop_loss.py) prima del cosmetico (dashboard)
#    Usare questo file come guida per capire cosa viene da main

# 6. Applicare migration 011 e 013 al DB del branch (se usa lo stesso)
#    /app/.venv/bin/python -m trdex.scripts.apply_migrations

# 7. Eseguire pytest — su main tutte le 334 passano.
#    Deltas attesi nel branch:
#    - Eventuali test LLM nuovi (branch-specific)
#    - Regression possibile se il branch ha già re-scritto StopLossMonitor

# 8. Settare TRDEX_CONFIG_ENCRYPTION_KEY nell'ambiente del branch
#    (Coolify se il branch ha un suo deploy separato, o local .env)

# 9. Smoke test: uv run python -m trdex.api (o lo script equivalente del branch)
#    - Verificare log: [credentials_crypto] at-rest encryption enabled (Fernet)
#    - Verificare log: [StopLoss] monitor started ... hydrated_events=N
#    - Verificare log: [tg-eval] scheduled — interval=3600s
```

---

## Dipendenze/vincoli esterni da sapere prima di mergere

1. **Fernet key**: il branch deve avere il proprio
   `TRDEX_CONFIG_ENCRYPTION_KEY` settato PRIMA del primo boot
   post-merge, altrimenti parte in passthrough e al successivo
   boot con la key criptando i plaintext legacy — non è un
   problema di correttezza ma causa un "doppio boot visibile"
   nei log. Generare con
   `python -m trdex.services.credentials_crypto`.
2. **Migration 011 + 013**: se il branch ha un proprio DB
   separato, vanno applicate. Il runner è idempotente.
3. **Telethon**: se il branch ha già disabilitato Telethon
   (settings `telegram_api_id=0`), il nuovo `telegram-evaluator`
   parte comunque (non dipende dal monitor) — verifica che non
   spammi i log con errori "no feeds" nella prima ora.
4. **Task Board**: è in questa repo, non deve essere mergato
   in llm-agents se il branch ha un proprio Task Board (verifica).

---

## Stato Step 1 Telegram lato utente (utile per chi fa il merge)

Blocker esterni al codice, gestiti dall'utente:
- [ ] 1.1 Credenziali Telegram da my.telegram.org → dashboard
- [ ] 1.2 Login one-time via `docker exec ... telegram_login.py`
- [ ] 1.3 Discovery chat_id dopo join Zanni canale
- Gate: 7 giorni di dati, `win_rate ≥ 0.6` e `roi_pct ≥ 5%` su
  ≥20 segnali resolved → pronti per Step 2 (auto-execute).

Se il branch llm-agents vuole contribuire a Step 2 del Telegram
(TelegramSignalExecutor con LLM scoring al posto del rule engine
first-touch), coordinarsi PRIMA del merge per evitare di scrivere
`telegram/executor.py` in entrambe le branch in modo divergente.

---

**Fine handoff.**

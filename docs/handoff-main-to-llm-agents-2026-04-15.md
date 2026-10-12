# Handoff: `main` → `llm-agents` worktree
**Data**: 2026-04-15
**From**: sessione su `C:\Users\Daniele\Antigravity\trdex\` (branch `main`)
**To**: sessione su `C:\Users\Daniele\Antigravity\trdex-llm\` (branch `llm-agents`)

## Obiettivo

Merge-forward di `main` in `llm-agents` per allineare il branch LLM con i
bug-fix di produzione e le modifiche strutturali fatte dal precedente
handoff (2026-04-11). La regola è: i fix di produzione si fanno su `main`
e vengono poi mergiati nel branch LLM, **mai il contrario**.

## Commit da mergiare (da `2026-04-11` in poi)

Elencati in ordine cronologico inverso (più recente in cima). Solo i
commit con impatto strutturale o di design meritano attenzione — gli
altri sono bug-fix o piccoli tweak che dovrebbero mergiare senza
conflitti.

### Sessione 2026-04-15 (questa)

- `a15bd84` — **feat: manual open/close positions + gate_min_days in Runtime Config**
  - Nuovi endpoint `POST /v1/portfolio/open` e `POST /v1/portfolio/close/{id}`
  - Dashboard: bottone Close per posizione + form Manual Open
  - `gate_min_days` ora editabile dal Runtime Config (dashboard)
  - Impatto LLM branch: nessuno strutturale, gli endpoint sono nuovi.
    Se `trdex-llm/` ha rifattorizzato `portfolio_routes.py`, conflitti
    facili da risolvere.

- `5725a3d` — **feat(strategy): improve signal quality — RSI momentum filter, SMA 9/21**
  - RSI filter: 40–60 zona neutrale → direzione (>50 BUY / <50 SELL) + overextension (>70 SELL / <30 BUY)
  - SMA periods: 5/13 → 9/21
  - SL/TP: 3%/5% → 2%/4%, trailing 2% → 1.5%
  - Simboli: 25 → 10 liquidi (BTC ETH SOL BNB XRP ADA AVAX LINK POL ATOM)
  - **Impatto LLM branch**: `src/trdex/agents/analyst.py` è il file-chiave
    che il branch `llm-agents` sta riscrivendo per sostituire il rule
    engine con LLM veri. **NON mergiare meccanicamente** — la logica RSI
    qui serve solo come baseline; nel branch LLM la decisione la
    prenderà il modello. Prendi nota dei nuovi valori SL/TP e del
    simbol set ridotto, applica direttamente la nuova config.

- `ac6217b` — **chore(config): reduce gate_min_days from 25 to 20**
  - Solo valore default in `config.py`. Merge pulito.

### Pre-2026-04-15 (già parzialmente coperti dall'handoff del 2026-04-11)

Se il merge di `2026-04-11` è ancora pendente, riferirsi a
`docs/handoff-main-to-llm-agents-2026-04-11.md` per quel batch.

## DB state su produzione (2026-04-15)

- **TRUNCATE eseguito**: `positions`, `account_balance`,
  `signal_outcomes`, `agent_runs`, `stop_loss_events`
- **Reseed**: $10,000 USDT deposit
- **Gate readiness**: 20 giorni (configurato via codice + Runtime Config)

Il DB del branch LLM (se usa lo stesso container `db`) vede già questo
stato. Se `trdex-llm/` usa un DB separato (es. container dedicato),
replicare il reset sul suo DB prima del prossimo dry-run.

## Decisioni di design confermate

1. **Strategia attuale ($2/giorno su $10k) è inaccettabile** — 0.02% daily
   non è un edge, è rumore. Le tre analisi LLM (Perplexity/Claude/Gemini
   in `docs/Risposte LLM Strategia/`) convergono: SMA cross su 5m è
   rumoroso, RSI 40–60 blocca il momentum, troppi simboli.

2. **Nuovi parametri in main** (baseline aggiornata per il branch LLM):
   - Timeframe: 1h (già era così)
   - SMA: 9/21
   - RSI filter: direzionale (>50 BUY / <50 SELL)
   - SL/TP: 2%/4% con trailing 1.5%
   - Simboli: 10 liquidi

3. **Runtime Config come source of truth**: tutti i threshold (SL/TP,
   gate days, sizing, drawdown) sono editabili da dashboard senza
   redeploy. Nel branch LLM lo stesso principio dovrebbe applicarsi a
   **prompt template** e **model selector** per ogni agente.

## Note operative

- **VPS**: host key è cambiata. Dopo il cambio, serve `ssh-keygen -R srv.gravya.it`
  e una connessione manuale per accettare il nuovo fingerprint prima di
  riprendere SSH automatizzato.
- **Fail2ban**: può bannare l'IP dopo tentativi SSH falliti. Unban via
  console web Hostinger: `sudo fail2ban-client set sshd unbanip <IP>`.
- **Quality gate Kloudify**: se si attiva durante una sessione, elimina
  manualmente `.claude/logs/.quality-gate-active` e `.claude/logs/.stuck-detected`.
  L'escape hatch in `check-quality-gate.sh:91` permette sempre di
  rimuovere i file del gate.

## Prossimi step nel branch `llm-agents`

1. Pull di `origin/main` e merge nel branch (`git merge origin/main`)
2. Risolvere i conflitti previsti in `analyst.py` (il rule engine è
   stato modificato, ma nel branch LLM viene sostituito)
3. Aggiornare i default SL/TP/simboli in config se non già fatto
4. Continuare il design doc `trdex-llm/.claude/reports/llm-agents-design-2026-04-08.md`
   (ancora da scrivere secondo memory.md)

# Baseline CI di `main`: problemi preesistenti

Questa cartella annota tutto ciò che oggi rende rossa la CI di `main`, con le liste complete e un piano per correggerla. Va **eliminata nell'ultimo commit della PR**, quando la CI è verde.

## Come è stato riprodotto

- `main` @ `18d8a33`, 2026-10-08.
- Stessi step di `.github/workflows/ci.yaml`: Python 3.12.13 e `uv sync --all-extras`, con le versioni del lock (ruff 0.15.9, mypy 1.20.0).
- La CI è rossa su ogni push a `main` almeno dal 2026-04-17.
- Il job si ferma al primo step (ruff), quindi **mypy e pytest in CI non sono mai stati eseguiti**; falliscono anche loro.

```bash
uv sync --all-extras
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest --cov=src/trdex --cov-report=term-missing
```

## Riepilogo

| Step | Problemi | Correggibili in automatico | Dump |
|---|---|---|---|
| `ruff check` | 275 | 201 con `--fix`, altri 15 con `--unsafe-fixes` | `ruff-check.txt` |
| `ruff format --check` | 86 file | tutti con `ruff format` | `ruff-format.txt` |
| `mypy src/` (strict) | 236 errori in 45 file | no | `mypy.txt` |
| `pytest` | 29 errori + 382 passati, coverage 43% | no (una sola causa) | `pytest.txt` |

## Piano consigliato, in quest'ordine

### 0. Coordinamento con le PR aperte

Formattare 86 file genera conflitti con tutto ciò che è in volo:
- su `main`: #3 (Dependabot), #4, #5, #6;
- il branch `llm-agents`, che riceve `main` con il merge forward.

Le PR #4, #5 e #6 sono rosse **solo** per questa baseline: non aggiungono finding nuovi rispetto a `main`.

Ordine che minimizza i conflitti:
1. Mergiare #4, #5 e #6 prima di questa PR. In alternativa, dopo questa PR, mergiare `main` in ciascun branch e rieseguire `ruff format` lì.
2. Fare `ruff format` in **un commit separato**, solo formattazione, e aggiungerne lo SHA a `.git-blame-ignore-revs`.
3. Su `llm-agents` eseguire lo stesso `ruff format`, con la stessa versione di ruff, **prima** del merge forward: i due lati arrivano con lo stesso stile e i conflitti si riducono alle modifiche reali.

### 1. pytest: 29 errori, una causa

`tests/test_audit_fixes.py` apre path assoluti Windows:
- riga 525: `"c:/Users/Daniele/Antigravity/trdex/docker-compose.yaml"`
- riga 583: `open("c:/Users/Daniele/Antigravity/trdex/.env.example")`

Fix: path relativi alla root del repo.

```python
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
path = REPO_ROOT / "docker-compose.yaml"
with open(REPO_ROOT / ".env.example") as f:
```

Verificato su una copia di `main`: con questo solo fix l'intera suite passa (411 test), quindi non ci sono altri fallimenti nascosti dietro questi errori.

### 2. ruff check: 201 correzioni automatiche

```bash
uv run ruff check src/ tests/ --fix
```

Grosso modo sono 114 `UP017`, 39 `I001`, 17 `F401`, 9 `RUF100` e 9 `UP037`, più gli altri `[*]` in `ruff-check.txt`.

⚠️ **Rompe un test**: `UP017` sostituisce `timezone.utc` con `UTC`, e `tests/test_audit_fixes.py:512` (`test_state_py_uses_timezone`) cerca la stringa `"timezone"` nel sorgente. Va aggiornato con una verifica di comportamento, per esempio che `MarketSnapshot().timestamp.tzinfo is not None` (lo fa già il test sopra), oppure cercando `"UTC"`. A parte questo, con le correzioni automatiche e il format tutta la suite passa.

### 3. ruff format: 86 file

```bash
uv run ruff format src/ tests/
```

Va in un commit dedicato (vedi punto 0).

### 4. ruff: 74 finding residui da correggere a mano

Conteggio dopo `--fix` e `format`, per regola. 15 di questi si correggono con `--unsafe-fixes` (tutti i B905, E731, RUF005 e RUF059, più 1 SIM102, 2 SIM103 e 2 SIM108): vanno applicati e poi rivisti nel diff. In particolare `zip(..., strict=True)` solleva un errore a runtime se le lunghezze differiscono.

| Regola | N | Note |
|---|---|---|
| RUF003 / RUF002 / RUF001 | 13 / 6 / 1 | caratteri Unicode ambigui (`–`, `×`, `−`) in commenti, docstring e stringhe: sostituire con ASCII |
| E402 | 11 | import non in testa al file: spostarli, oppure `# noqa: E402` dove l'ordine è voluto |
| **RUF006** | 7 | **probabile bug reale**, vedi sotto |
| SIM102 / SIM103 / SIM108 | 5 / 3 / 3 | semplificazioni |
| E731 | 4 | lambda assegnata: usare `def` |
| N802 / N806 | 4 / 4 | nomi di test con suffissi `_THE_FIX`, `_D13_D14`: rinominare in minuscolo o `# noqa: N802` |
| RUF012 | 3 | attributi di classe mutabili nei test: `ClassVar` o tuple |
| B904 | 2 | `raise ... from exc` in `market/feeds/yfinance.py:131,188` |
| B905 | 2 | `zip(..., strict=True)` |
| RUF005 / RUF059 / E741 | 2 / 2 / 1 | stile |
| F821 | 1 | `scripts/smoke_level1.py:79`: `AsyncEngine` usato solo in un'annotazione stringa; importarlo sotto `TYPE_CHECKING` |

### 5. mypy: 236 errori in modalità strict

Per codice di errore:

| Codice | N | Tipo |
|---|---|---|
| no-untyped-def | 65 | annotazioni mancanti (rumore della modalità strict) |
| type-arg | 62 | generici senza parametri, es. `dict` → `dict[str, Any]` |
| dict-item | 20 | **una sola causa**: `services/runtime_config.py`, `_KEY_REGISTRY` annotato `tuple[str, type]` ma con `None` come primo elemento → `tuple[str \| None, type]` |
| no-any-return | 19 | `warn_return_any` |
| no-untyped-call | 14 | conseguenza di no-untyped-def |
| attr-defined | 13 | 5 sono `Result.rowcount` nei repo SQLAlchemy (usare `CursorResult`/`cast`); 3 in `risk/stop_loss.py:536-538` perché `symbol_overrides` è annotato `dict[str, object]` |
| operator | 9 | tutti su `backtest/engine.py:236`, tipi di polars |
| assignment | 9 | |
| arg-type | 8 | tra cui `risk/stop_loss.py:409`: `closed_by` passato come `str` invece del `Literal` |
| unused-ignore | 7 | `# type: ignore` non più necessari |
| import-untyped | 4 | `yfinance`, `plotly`, `pandas`: override `ignore_missing_imports` o `pandas-stubs` |
| union-attr / comparison-overlap / untyped-decorator | 3 / 2 / 1 | |

Senza `strict` gli errori scendono a **85 in 21 file**: restano solo i problemi di tipo reali, senza le annotazioni mancanti. Due strade:
- **A, tutto subito**: correggere i 236. Le correzioni di massa sono `type-arg` e `no-untyped-def`.
- **B, a tappe**: tenere `strict = true` e aggiungere in `pyproject.toml` degli `[[tool.mypy.overrides]]` con `disallow_untyped_defs = false` per i moduli legacy (dashboard, scripts, api/app), da togliere man mano. I quick win della tabella valgono comunque: circa 30 errori con poche righe.

### 6. Workflow `.github/workflows/ci.yaml`

- **Filtro `paths`**: la CI parte solo per modifiche a `src/**`, `tests/**` e `pyproject.toml`. Una PR che tocca solo `ci.yaml`, `scripts/` o `docs/` **non esegue la CI**, e questa PR inclusa finché non tocca `src/` o `tests/`. Conviene aggiungere `.github/workflows/**`, `scripts/**` e `uv.lock`.
- **Branch**: la CI gira solo sulle PR verso `main`. Le PR verso `llm-agents` (#7, #8, #9) non hanno CI; aggiungere `llm-agents` a `branches`.
- **`scripts/` non è sotto lint**: `ruff check src/ tests/` esclude `scripts/backtest/`, che però ha dei test.
- **Annotazioni GitHub sui run**: `actions/checkout@v4` e `astral-sh/setup-uv@v4` usano Node 20, deprecato e forzato su Node 24, quindi vanno aggiornate a versioni che girano su Node 24. Inoltre `ubuntu-latest` passa a Ubuntu 26 dal 2026-10-19.

## Probabili bug reali emersi dall'analisi statica

Non sono solo stile: vanno corretti con attenzione.

1. **Task asyncio non referenziati (RUF006)**. Il loop tiene solo un riferimento debole ai task: un task creato e non salvato può essere raccolto dal garbage collector a metà esecuzione. Correzione tipica: salvarli in un `set` e rimuoverli con `task.add_done_callback(set.discard)`. Punti:
   - `api/app.py:511`, `:512`: hot-reload dei canali Telegram;
   - `api/app.py:658`, `:729`, `:761`: start e stop del monitor;
   - `context/scheduler.py:62`;
   - `market/manager.py:102`.
2. **`portfolio/service.py:72-76`**. Con `asyncio.gather(..., return_exceptions=True)` il codice controlla `isinstance(result, Exception)`, ma `CancelledError` è una `BaseException`: in quel caso si arriva a `result.price` e si ottiene un `AttributeError`. Usare `BaseException`. È anche il finding mypy `union-attr` a riga 76.

Gli altri finding mypy su `api/app.py` (stati sentinella `"starting"`/`"stopping"` nello stesso dict dei monitor, `_exchange` sul feed) e su `memory/context.py` (variabile `repo` riusata con tipi diversi) sono solo di tipizzazione: il comportamento a runtime è corretto.

## Checklist

- [ ] 0. Ordine di merge deciso (#3, #4, #5, #6 e `llm-agents`)
- [ ] 1. Path in `tests/test_audit_fixes.py` → 29 errori pytest risolti
- [ ] 2. `ruff check --fix` + aggiornamento di `test_state_py_uses_timezone`
- [ ] 3. `ruff format` in un commit dedicato + `.git-blame-ignore-revs`
- [ ] 4. 74 finding ruff residui (RUF006 e `BaseException` con test)
- [ ] 5. mypy, strada A o B
- [ ] 6. Workflow: `paths`, branch `llm-agents`, lint di `scripts/`, versioni delle actions
- [ ] CI verde su questa PR → eliminare `docs/ci-baseline/`

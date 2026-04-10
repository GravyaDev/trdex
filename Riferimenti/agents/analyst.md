---
doc_id: kb_analyst
agent: analyst
version: 1.0
last_updated: 2026-04-06
purpose: |
  Knowledge base completa e autosufficiente per l'Analyst Agent di trdex.
  Contiene SOLO i blocchi rilevanti per questo agente.
  Nessuna dipendenza da altri documenti.
sources:
  - notebook_id: 23eff711-d90f-4575-9a2f-5d1244681d9e
schema:
  HARD: "Regole immutabili"
  PARAM: "Parametri configurabili"
  HEUR: "Euristiche evolvibili con review umana"
  PROMPT: "Template di system prompt"
---

# Analyst Agent Knowledge Base

> L'Analyst Agent calcola indicatori tecnici, classifica volatilità e produce un signal con confidence.
> Non decide se eseguire l'ordine (lo fa il Risk Manager). Non scrive ordini (lo fa l'Executor).

---

## 1 — IDENTITÀ E FILOSOFIA

### `HARD-MIND-001` — Probabilistic Mindset
**Tags**: `mindset`

```yaml
rule: probabilistic_mindset
principle: |
  Ogni signal ha esito incerto. Il vantaggio si manifesta solo su grande campione.
  Mai modificare i parametri di un indicatore in base a un singolo risultato.
hard_constraint: |
  Mai abbandonare una strategia codificata solo per N perdite consecutive.
source: "Mark Douglas — Trading in the Zone"
```

### `HARD-MIND-002` — Negative Constraints
**Tags**: `prohibited_actions`

```json
{
  "prohibited_actions": [
    "override_indicator_math_with_intuition",
    "modify_thresholds_during_runtime",
    "emit_signals_with_confidence_below_0.40",
    "ignore_volume_divergence",
    "skip_OBV_validation"
  ]
}
```

---

## 2 — RUOLO OPERATIVO

### `HARD-ANALYST-001` — Scope of Work
**Tags**: `scope, role`

```yaml
agent: analyst
input:
  - market: MarketSnapshot (OHLCV candles)
  - sentiment: SentimentContext (from Scout)
output:
  - AnalysisResult:
      signal: "BUY" | "SELL" | "HOLD"
      confidence: float [0.0, 1.0]
      reasoning: string
      indicators: dict[str, float]
allowed_actions:
  - compute technical indicators
  - aggregate signals via rule engine
  - write entity_graph facts (volatility_regime)
forbidden_actions:
  - call execution gateway
  - modify portfolio state
  - approve/block orders (compito del Risk Manager)
```

---

## 3 — INDICATORI TECNICI

### `PARAM-IND-001` — RSI
**Tags**: `indicator, rsi, momentum`

```yaml
indicator: RSI
period: 14
smoothing: Wilder           # com=period-1
implementation: trdex/backtest/indicators.py
thresholds:
  oversold: 30              # → BUY
  overbought: 70            # → SELL
confidence_weights:
  oversold: 0.6
  overbought: 0.6
  neutral: 0.3
```

### `PARAM-IND-002` — MACD
**Tags**: `indicator, macd, divergence`

```yaml
indicator: MACD
fast_period: 12
slow_period: 26
signal_period: 9
primary_signal: divergence
divergence_logic:
  bullish:
    price: lower_low
    macd_histogram: higher_low
    meaning: "potenziale inversione rialzista"
  bearish:
    price: higher_high
    macd_histogram: lower_high
    meaning: "potenziale inversione ribassista"
note: "Divergenze più affidabili dei crossover semplici"
```

### `PARAM-IND-003` — Bollinger Bands
**Tags**: `indicator, bollinger, volatility`

```yaml
indicator: BollingerBands
period: 20
std_dev: 2
purpose: "Misura deviazione del prezzo dalla media a lungo termine"
signals:
  squeeze: "bande strette → bassa volatilità → in attesa di breakout"
  band_touch: "Touch della banda esterna ≠ segnale automatico (rischio fakeout)"
warning: "MAI usare touch della banda come unico signal"
```

### `PARAM-IND-004` — Moving Averages
**Tags**: `indicator, sma, ema, trend`

```yaml
trdex_default:
  type: SMA
  short: 9
  long: 21
  reason: "Veloce per il timeframe agent cycle"

alternative_setups:
  day_trading:
    type: SMA
    periods: [20, 50, 200]
    uptrend_alignment: "20 > 50 > 200"
    downtrend_alignment: "20 < 50 < 200"
    confidence_when_aligned: 0.7

  hourly:
    type: EMA
    periods: [7, 25, 99]
    optional_extra: 50
```

### `PARAM-IND-005` — Fibonacci Retracements
**Tags**: `indicator, fibonacci`

```yaml
levels:
  retracements: [0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]
  extensions: [1.618, 2.618, 3.618]
golden_ratio: 0.618
key_zones_for_entry: [0.500, 0.618]
golden_rule: |
  Nella maggior parte dei casi il rimbalzo si ferma
  nell'area compresa tra 0.382 e 0.618.
extension_use: "Predire top esaurimento del trend (5° onda Elliott)"
```

### `PARAM-IND-006` — On Balance Volume (OBV)
**Tags**: `indicator, obv, volume, validator`

```yaml
indicator: OBV
purpose: "Misura accumulazione/distribuzione comparando prezzo e volume"
role: PRIMARY_VALIDATOR
critical_rule: |
  Se il prezzo rompe un livello ma OBV non mostra accumulation:
  → flagga come LOW_PROBABILITY_DIVERGENCE
  → forza il signal a HOLD
```

### `HEUR-IND-001` — Signal Aggregation Rule Engine
**Tags**: `aggregation, evolvable`

```python
def aggregate_signals(rsi, sma_short, sma_long, sentiment, volume_confirm):
    """
    HEUR: i pesi possono evolvere con l'esperienza (review umana).
    """
    signals = []

    # RSI
    if rsi < 30:
        signals.append(("BUY", 0.6, f"RSI={rsi:.1f} oversold"))
    elif rsi > 70:
        signals.append(("SELL", 0.6, f"RSI={rsi:.1f} overbought"))
    else:
        signals.append(("HOLD", 0.3, f"RSI={rsi:.1f} neutral"))

    # SMA
    if sma_short > sma_long:
        signals.append(("BUY", 0.5, "SMA bullish"))
    else:
        signals.append(("SELL", 0.5, "SMA bearish"))

    # Sentiment from Scout
    if sentiment > 0.3:
        signals.append(("BUY", 0.2, f"sentiment +{sentiment:.2f}"))
    elif sentiment < -0.3:
        signals.append(("SELL", 0.2, f"sentiment {sentiment:.2f}"))

    # OBV validator (HARD)
    if not volume_confirm:
        return ("HOLD", 0.0, "Volume divergence — low probability")

    buy_conf = sum(c for s, c, _ in signals if s == "BUY")
    sell_conf = sum(c for s, c, _ in signals if s == "SELL")

    if buy_conf > sell_conf and buy_conf >= 0.4:
        return ("BUY", min(buy_conf, 1.0), "; ".join(n for _, _, n in signals))
    if sell_conf > buy_conf and sell_conf >= 0.4:
        return ("SELL", min(sell_conf, 1.0), "; ".join(n for _, _, n in signals))
    return ("HOLD", 0.0, "Insufficient confidence")
```

### `HARD-ANALYST-002` — Confidence Floor
**Tags**: `confidence, threshold`

```yaml
rule: minimum_confidence_emission
threshold: 0.40
action: |
  Mai emettere BUY/SELL con confidence < 0.40.
  Se confidence < 0.40 → forza HOLD.
```

---

## 4 — CANDLESTICK PATTERNS

### `HARD-CDL-001` — Candlestick Anatomy
**Tags**: `candlestick, basics`

```yaml
bullish_candle:
  color: green/white
  open: bottom_of_body
  close: top_of_body
  meaning: "prezzo salito nel periodo"

bearish_candle:
  color: red/black
  open: top_of_body
  close: bottom_of_body
  meaning: "prezzo sceso nel periodo"

wicks:
  upper: "punto massimo (high)"
  lower: "punto minimo (low)"
```

### `HEUR-CDL-001` — Pattern Classification
**Tags**: `candlestick, evolvable`

```yaml
reversal_signals:
  feature: trend_exhaustion
  patterns:
    - doji
    - hammer
    - inverted_hammer
    - hanging_man
    - shooting_star
    - bullish_engulfing
    - bearish_engulfing
    - evening_star
    - morning_star
    - three_black_crows
    - three_white_soldiers

continuation_signals:
  feature: momentum_confirmed
  patterns:
    - bullish_flag
    - bearish_flag
    - pennant
    - ascending_triangle
    - descending_triangle

confidence_logic: |
  IF pattern == "bullish_flag" AND current_trend == "up":
      confidence_score += 0.15
  IF pattern == "doji" AND at_support_resistance:
      flag_as_potential_reversal = True
```

### `HEUR-CDL-002` — Trend Detection
**Tags**: `trend, elliott_waves, evolvable`

```yaml
methods:
  line_charts: "usare per identificare trend big-picture filtrando rumore"
  elliott_waves:
    structure: "5 onde direzionali + correzione A-B-C"
    exhaustion_signal: "completamento 5° onda"
    fibonacci_confluence:
      extensions: [2.618, 3.618]
      use: "predire top esaurimento"

trdex_default: "SMA crossover con confirmation OBV (HEUR-IND-001)"
```

---

## 5 — SMART MONEY CONCEPTS (SMC)

### `HEUR-SMC-001` — Break of Structure (BOS)
**Tags**: `smc, bos, continuation`

```yaml
pattern: break_of_structure
sequence:
  1: "trend in corso"
  2: "impulso direzionale"
  3: "pullback"
  4: "rottura del massimo recente al rialzo (per uptrend)"
signal: trend_continuation
```

### `HEUR-SMC-002` — Change of Character (CHOCH)
**Tags**: `smc, choch, reversal`

```yaml
pattern: change_of_character
condition: "All'interno di un trend, prodotto un nuovo minimo"
signal: behavior_mutation
use: "Setup di entry contro-trend"
```

### `HEUR-SMC-003` — Fair Value Gaps (FVG)
**Tags**: `smc, fvg`

```yaml
pattern: fair_value_gap
detection: |
  Aree create da forti spinte di prezzo dove NON vi sono
  sovrapposizioni (overlap) tra candele adiacenti.
entry_rule: |
  1. Identifica il gap (scatola sul grafico)
  2. Attendi che il prezzo rintracci verso il gap
  3. Entry al MIDPOINT del gap
expected: "Il prezzo continua nel suo movimento originario"
```

### `HEUR-SMC-004` — Support/Resistance Validation
**Tags**: `smc, support_resistance, breakout, fakeout`

```yaml
identification:
  method: "Tracciare linee orizzontali/trendline su 2+ pivot"
  retest: "Aspettare segnale di rimbalzo prima di considerare valido"

breakout_validation:
  rule: VOLUME_CONFIRMATION
  steps:
    - "Quando prezzo rompe un livello uscendo da fase laterale"
    - "Analizza volume della candela di rottura"
    - "Volume >>> medie precedenti → breakout VALIDO"
    - "Volume basso/normale → probabile FAKEOUT, NON segnalare"
```

---

## 6 — VOLATILITY CLASSIFICATION

### `HARD-ANALYST-003` — Volatility Regime
**Tags**: `volatility, classification`

```python
def classify_volatility_regime(candles, window=20):
    """
    Classifica il regime di volatilità basato sul coefficiente di variazione.
    """
    closes = [c.close for c in candles[-window:]]
    if len(closes) < 5:
        return "unknown", None

    mean = sum(closes) / len(closes)
    std = (sum((x - mean) ** 2 for x in closes) / len(closes)) ** 0.5
    cv = std / mean if mean > 0 else 0

    if cv < 0.01:
        regime = "low"
    elif cv < 0.03:
        regime = "medium"
    else:
        regime = "high"

    return regime, cv

# Output: scrivi in entity_graph come predicate=volatility_regime
```

---

## 7 — MULTI-TIMEFRAME ANALYSIS

### `HEUR-ANALYST-MTF-001` — Multi-Timeframe Confirmation
**Tags**: `multi_timeframe, evolvable`

```yaml
default_timeframes:
  trend: 4h        # macro direction
  setup: 1h        # entry setup
  timing: 15m      # precise timing

rule: |
  Il signal su {setup} è valido SOLO se il trend su {trend} è coerente.
  No contro-trend trades senza confirmation strong.

implementation_status: "Da implementare in trdex (oggi è single-timeframe)"
```

---

## 8 — MEMORIA E ENTITY GRAPH

### `HARD-ANALYST-MEM-001` — Entity Graph Writes
**Tags**: `entity_graph, memory, mandatory`

```yaml
write_pattern:
  - subject_type: symbol
    subject_id: "{symbol}"
    predicate: volatility_regime
    object_value:
      regime: "low" | "medium" | "high"
      cv: float
    source: analyst
    note: "run_id={run_id}"

read_pattern:
  - subject_type: symbol
    subject_id: "{symbol}"
    predicate: volatility_regime
    use: "context comparison con regime precedente"
```

### `HEUR-ANALYST-MEM-002` — Experience Loop
**Tags**: `evolution, learning`

```yaml
experience_data_source: agent_runs (DB table)
loop:
  - analyze: pattern di setup vincenti vs perdenti
  - identify: in quali regimi di volatilità l'edge si materializza
  - propose: aggiornamenti ai pesi di HEUR-IND-001 (review umana)
constraints:
  - "Mai modificare HARD blocks automaticamente"
  - "Mai auto-applicare modifiche ai pesi senza review"
```

---

## 9 — PROMPT TEMPLATE

### `PROMPT-ANALYST-001`
**Tags**: `prompt, analyst`

```text
Sei l'Analyst Agent di trdex.
Il tuo compito è ANALIZZARE i dati tecnici e produrre un signal con confidence.

INPUT:
- market: MarketSnapshot con candles OHLCV
- sentiment: SentimentContext dallo Scout

REGOLE INVIOLABILI:
- Mai emettere BUY/SELL con confidence < 0.40 (HARD-ANALYST-002)
- Volume divergence (OBV) → forza HOLD (PARAM-IND-006)
- Mai override matematico degli indicatori
- Non sei tu a decidere l'esecuzione (compito del Risk Manager)

AZIONI:
1. Calcola indicatori: RSI(14) Wilder, SMA(9), SMA(21)
2. Classifica volatility_regime (HARD-ANALYST-003)
3. Aggrega segnali via HEUR-IND-001 rule engine
4. Scrivi volatility_regime nell'entity_graph
5. Restituisci AnalysisResult(signal, confidence, reasoning, indicators)

OUTPUT:
AnalysisResult(
  signal: "BUY" | "SELL" | "HOLD",
  confidence: float [0.0, 1.0],
  reasoning: "spiegazione concisa basata sui segnali aggregati",
  indicators: {rsi, sma_9, sma_21, volatility_cv, ...}
)
```

---

## 10 — HISTORICAL CONTEXT (RAG)

### `HEUR-ANALYST-RAG-001` — Market Brief & Historical Episodes
**Tags**: `rag, memory, episodes, market_brief`

```yaml
market_brief:
  source: memory/market_brief.py
  injection: prompt section 0 (before technical indicators)
  content: |
    Static snapshot of current conditions: price, 24h change, volatility
    regime, RSI zone, SMA alignment, volume activity, short-term trend.
    Always present when candles are available. Small token footprint.

historical_episodes:
  source: memory/market_episodes.py
  collection: trdex_market_episodes
  injection: Tier 4b in memory snapshot (via MemoryContextLoader)
  content: |
    Semantically similar past market regimes retrieved from Qdrant.
    Episode types: trend_reversal, volatility_spike, volume_surge,
    consolidation_breakout, regime_change. Each includes price change %,
    RSI, volume ratio, SMA state, volatility CV.
  usage: |
    When historical episodes are present in the memory snapshot, use them
    as analogical evidence. If a similar past episode led to a reversal,
    factor that into confidence calibration — but never override indicator
    math based on a single historical analogy.
  limit: 3 episodes per query (configurable via similar_episodes_limit)
```

---

## 11 — RIFERIMENTI

### `REF-ANALYST-001` — Implementation Files

```yaml
agent_file: src/trdex/agents/analyst.py
indicators_file: src/trdex/backtest/indicators.py
entity_graph_repo: src/trdex/storage/entity_graph_repo.py
market_brief: src/trdex/memory/market_brief.py
market_episodes: src/trdex/memory/market_episodes.py
backfill_script: src/trdex/scripts/backfill_ohlcv.py
generate_script: src/trdex/scripts/generate_episodes.py
```

### `REF-ANALYST-002` — Source Books

```yaml
- "Trading in the Zone — Mark Douglas (mindset)"
- "Japanese Candlestick Charting Techniques — Steve Nison (patterns)"
- "Technical Analysis of the Financial Markets — John J. Murphy (indicators)"
```

---

**FINE KB ANALYST**

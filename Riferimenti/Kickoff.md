Sei sul branch llm-agents del progetto trdex (AI trading automation, Python 3.12, LangGraph, FastAPI, TimescaleDB, Qdrant). Il branch è stato creato ieri sera da main per un motivo preciso: gli "agent" attuali (Scout, Analyst, Risk, Executor) sono un rule engine deterministico di if/else, non c'è nessun LLM dentro. L'Analyst fa SMA cross + RSI + sentiment averaging in una funzione _rule_based_signal() di 50 righe. Il commento nel file dice "LLM-style reasoning" ma è falso — è puro Python math senza alcuna chiamata a modelli AI.

Il tuo compito è progettare e poi implementare la trasformazione di trdex in un sistema realmente AI-powered. Prima scrivi il design doc, poi (nelle sessioni successive) il codice.

4 decisioni architetturali già prese:

LangChain abstractions per flessibilità provider. L'operatore deve poter scegliere tra Claude (Anthropic), GPT (OpenAI), Gemini (Google) per ogni agente indipendentemente, senza toccare codice. Usa langchain-anthropic, langchain-openai, langchain-google-genai come adapter.

Dashboard config pages per i 4 agenti. Nel Streamlit dashboard (src/trdex/dashboard/app.py, 381 righe, già deployato su /dashboard/), aggiungere 4 pagine di configurazione — una per Scout, una per Analyst, una per Risk, una per Executor. Ogni pagina permette di: editare il system prompt dell'agente (textarea con default sensato pre-popolato da te), settare i parametri di sampling (temperature, max_tokens, top_p — con default), selezionare il modello LLM da un dropdown (Claude Haiku/Sonnet/Opus, GPT-4o/4o-mini, Gemini Flash/Pro). I default devono essere pensati per un uso reale di trading crypto, non generici. Persistenza dei settings in DB (tabella agent_config o simile).

Reflection memory dal day 1. Ogni agente, prima di decidere, legge la propria storia di trade recenti dal DB. L'infrastruttura esiste già: Tier 6 narrative memory (agent_runs table con intent, confidence, reasoning, order_status), entity graph (entity_graph table con subject/predicate/object facts), agent_memory table. Oggi questi dati vengono scritti ma mai letti dall'Analyst nelle sue decisioni. Il nuovo Analyst LLM deve riceverli come context nel prompt: "nelle ultime 48h hai fatto X trade su BTC, Y vincenti Z perdenti, pattern osservato: ...".

Multi-agent reale dal day 1. Ogni nodo del LangGraph (Scout, Analyst, Risk, Executor) fa una chiamata LLM separata con il suo prompt, il suo modello, e il suo contesto specifico. Non un unico LLM call monolitico. Questo dà debug surface migliore (vedi cosa ha pensato ogni agente separatamente) e flessibilità (puoi mettere Haiku su Scout per velocità e Sonnet su Analyst per qualità).

File chiave da leggere prima di scrivere il design doc (sono tutti in questo repo, stessi file di main):

src/trdex/agents/analyst.py — il rule engine attuale da sostituire, specialmente _rule_based_signal()
src/trdex/agents/scout.py — come lo Scout raccoglie dati (market data + Qdrant context retrieval)
src/trdex/agents/risk.py — i 4 risk gates (questo potrebbe restare deterministico o diventare LLM-augmented)
src/trdex/agents/executor.py — il nodo executor con idempotency keys
src/trdex/agents/state.py — lo state machine condiviso tra i nodi (AgentState, AnalysisResult, PortfolioContext)
src/trdex/agents/intent.py — l'Intent enum (OPEN_LONG, CLOSE_LONG, HOLD, ecc) e il translator signal_to_intent
src/trdex/agents/scheduler.py — il loop dello scheduler che chiama il graph ogni 5 min
src/trdex/dashboard/app.py — il dashboard Streamlit dove aggiungere le 4 config pages
src/trdex/agents/memory_helpers.py — come la memory 6-tier è caricata (ma non usata) oggi
src/trdex/context/vector_store.py — Qdrant store per news context retrieval

Costo operativo da tenere a mente nel design: con 5 symbols × tick ogni 5 min × active hours 14h/giorno = ~840 cicli/giorno. Se ogni ciclo fa 4 LLM call (uno per agente): 3360 call/giorno. Con Claude Haiku a ~$0.005/call stimato → ~$17/giorno → ~$500/mese. Troppo. Ottimizza: Haiku per Scout e Risk (veloci, poco context), Sonnet solo per Analyst (la decisione che conta). Oppure proponi un'architettura dove Scout e Risk restano deterministici e solo l'Analyst diventa LLM. Documenta i trade-off nel design doc.

Primo output richiesto: scrivi .claude/reports/llm-agents-design-2026-04-08.md con:

Stato attuale onesto (cosa fa veramente ogni agente oggi)
Architettura target per ogni agente (cosa cambia, cosa resta)
Cost model dettagliato (quale LLM per quale agente, token/call, call/giorno, $/mese)
Schema DB per agent_config (persistenza settings dashboard)
Prompt template default per ogni agente LLM (il testo reale, non placeholder)
Implementation roadmap ordinata per dependency (6-8 task con effort)
Testing strategy (come verificare che l'LLM dà risposte sensate)
Risk & mitigations (hallucination, costi fuori controllo, latenza, prompt injection da news)
Non scrivere codice in questa sessione. Solo il design doc. Il codice viene dopo, quando io ho rivisto e approvato il piano.
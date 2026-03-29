---
description: Brainstorm ideas in isolation — discuss, evaluate, promote to tomorrow's Task Board
argument-hint: "[optional seed idea]"
allowed-tools:
  - Read
  - Edit
  - Bash(date:*)
---

Modalità brainstorm isolata. Discuti idee liberamente senza toccare il lavoro in corso. Le idee promosse vanno in Task Board → Today per la sessione successiva.

## Steps

### Step 1: Setup (read-only)

Leggi in parallelo:
- `Task Board.md` — per sapere cosa c'è già in Today/This Week ed evitare duplicati
- `.claude/memory.md` — per contestualizzare le idee rispetto al lavoro in corso

**Non modificare nulla. Nessuna scrittura in questo step.**

Tieni a mente il contesto caricato ma non menzionarlo a meno che non sia rilevante per le idee discusse.

### Step 2: Apertura modalità

Annuncia con un messaggio breve:

> **Modalità brainstorm attiva.** Tutto quello che diciamo qui è isolato dal lavoro in corso — niente tocca memoria, scratchpad o daily notes. Le idee che promuoviamo finiranno in Task Board domani mattina.

Se c'è un argomento seed (`$ARGUMENTS`), usalo come punto di partenza immediato.
Altrimenti chiedi: "Cosa hai in mente?"

### Step 3: Loop conversazionale

Per ogni idea introdotta dall'utente, segui questo schema — adatta il tono alla conversazione, non essere meccanico:

1. **Capire l'obiettivo reale**
   - "Cosa stai cercando di risolvere con questo?"
   - "Qual è il risultato concreto che ti aspetti?"

2. **Espandere e connettere**
   - Proponi varianti o angolazioni alternative
   - Collega a cose già in corso (usa il contesto caricato)
   - Segnala rischi o dipendenze non ovvie

3. **Valutare insieme**
   - Dimensione: task singolo / feature / refactor architetturale / esperimento
   - Urgenza: bloccante / utile ora / backlog
   - Valore atteso vs. complessità

4. **Classificare provvisoriamente**
   - `[CANDIDATA]` — ha senso fare, value chiaro, fattibile
   - `[PARCHEGGIATA]` — buona idea ma timing sbagliato o manca contesto
   - `[SCARTATA]` — yak shaving, duplicato, o valore troppo basso

Continua il loop finché l'utente non chiude la sessione con "basta", "chiudi", "fine", o simili.

Claude può proporre promozione o scarto di una idea se ha ragioni concrete — l'utente decide sempre.

### Step 4: Resoconto

Quando l'utente chiude, produci un riepilogo in output (NON scritto su nessun file):

```
## Sessione brainstorm — [DATA ORA]

### Promosse → Task Board domani
- **[titolo idea]**: [descrizione concisa — una riga]
...

### Parcheggiate
- **[titolo idea]**: [perché parcheggiata]
...

### Scartate
- **[titolo idea]**: [perché]
...
```

Se non ci sono idee in una categoria, ometti quella sezione.

### Step 5: Promozione al Task Board

Per ogni idea classificata come "promossa":

1. Leggi `Task Board.md`
2. Aggiungi ogni idea promossa alla sezione **Today** con il prefisso `[idea]`:
   ```
   - [ ] [idea] <titolo conciso> — <una riga di contesto>
   ```
3. Inserisci le voci alla fine della sezione Today (dopo i task esistenti)

**Non toccare**: `memory.md`, `Scratchpad.md`, `Daily Notes/`, nessun altro file.
**Nessun commit.** La scrittura su Task Board è l'unica azione di output.

Se non ci sono idee promosse, non scrivere nulla — chiudi con il resoconto e basta.

### Note operative

- Il prefisso `[idea]` permette a `/start` di distinguere le idee promosse dai task operativi e trattarle separatamente (chiedere se avviarle, spostarle in This Week, o tenerle in Today)
- Se un'idea è già presente in Task Board o This Week, segnalalo durante la discussione anziché duplicare al momento della promozione
- Niente Agent calls — questa modalità è sincrona e leggera per design

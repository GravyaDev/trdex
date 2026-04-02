# Registro Operazioni AI — {{PROJECT_NAME}}

> **Scopo:** Tracciabilità completa di ogni processo AI. Nessuna black box.
> **Ultimo aggiornamento:** {{DATE}}
> **Politica:** Ogni operazione AI deve essere registrata con chi, cosa, dove, come e perché.
> **Aggiornamento:** Settimanale (venerdì, wrap-up Step 6d)

---

## Indice

| Sezione | File | Descrizione |
|---|---|---|
| Architettura operativa | [architecture-map.md](architecture-map.md) | Mappa mentale + albero gerarchico agenti |
| Catena decisionale | [decision-chain.md](decision-chain.md) | Flow richiesta→risultato + decision framework |
| Registro processi | [processes.md](processes.md) | Processi attivi e pianificati con HITL level |
| Matrice tracciabilità | [traceability.md](traceability.md) | Dove si registra ogni tipo di evento |
| Schema escalation | [escalation.md](escalation.md) | Albero escalation + trigger incondizionati |
| Gap noti | [gaps.md](gaps.md) | Gap di tracciabilità con priorità fix |

---

## Principi

1. **Nessuna black box** — ogni decisione AI ha un log con chi, cosa, perché
2. **HITL progressivo** — `full_manual` → `escalation` → `low_risk` → `full_auto`, promosso solo dai partner umani
3. **Escalation incondizionata** — spese reali, impatti irreversibili e giudizi creativi vanno SEMPRE ai partner umani
4. **Costo tracciato** — ogni chiamata LLM registra modello, token, costo

---

## Cambiamenti architetturali significativi

| Data | Cambiamento |
|---|---|
| {{DATE}} | Registro iniziale |

---

*Documento vivo — aggiornato ogni venerdì al wrap-up.*

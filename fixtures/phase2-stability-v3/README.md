# Stability diagnostic v3

Synthetic authored diagnostic, not an independent benchmark. Eight development and twelve final intents, each with three paraphrases. Questions are unchanged from v2; v1 was rejected for semantic issues and v2 growth was rejected because all new documents were outside the target projects. This version adds same-project records for explicitly different tasks, exact copies, historical/private records, and unrelated projects. All facts and IDs are stable under document growth; order_seed only permutes sources. Noise is template-generated and is not a sample of real Notion usage.

The generator contains source records only. Retrieval and API inputs must never include scoring fields. The final evaluator must check a saved selection before opening final.json. Gold is a finite diagnostic checklist, not proof that every relevant fact has been found.

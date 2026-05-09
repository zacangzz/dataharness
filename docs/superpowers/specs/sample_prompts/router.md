Route the user turn into exactly one intent.

Allowed intents:
- `ANALYSIS`
- `CONVERSATIONAL`

Rules:
- Prefer `ANALYSIS` when the user is asking for data work, investigation, transformation, validation, or artifact-producing analysis.
- Prefer `CONVERSATIONAL` when the user is asking for explanation, orientation, or discussion that does not require running analysis steps.
- Return strict JSON only.

Response shape:
```json
{"intent":"ANALYSIS","confidence":0.0,"reason":"short reason"}
```

Return strict JSON only.

The review output may propose updates under:
- `preference_updates`
- `dataset_knowledge_updates`
- `workflow_notes`
- `quality_observations`

Rules:
- Keep review advisory.
- Do not modify prompts, tools, or harness code.
- Do not propose autonomous self-improvement actions.
- Ground observations in the completed work and its artifacts.

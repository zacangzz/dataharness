You are performing a DataHarness context checkpoint compaction for a local-first data-analysis TUI. Create a handoff summary for the next LLM turn that will continue this exact chat.

Return only the compacted summary. Start exactly with `Summary of compacted chat:`. Use these bullet labels when relevant:
- Current user goal
- Progress and facts
- Data/workspace references
- Constraints and preferences
- Next steps

Preserve concrete DataHarness context:
- workspace file paths, schemas, columns, and dataset relationships
- computed results and execution evidence
- tool and command outcomes
- active plans, step ids, pending approvals, and unresolved failures
- app-layer constraints or layer-boundary findings
- user preferences and open questions

Merge any prior `compacted_summary` content into the new summary instead of quoting it.

Do not copy transcript lines, role prefixes, greetings, or filler. Ignore greetings, test messages, and one-word acknowledgements unless they changed the task. Do not mention that messages were compacted. Be concise and make the next LLM able to continue without asking the user to repeat context.

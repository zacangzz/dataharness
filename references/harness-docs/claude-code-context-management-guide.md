# Claude Code Context Management: 4 Surgical Layers

Source: https://github.com/NeuZhou/awesome-ai-anatomy/tree/main/claude-code  
Primary file: `src/query.ts` (~1,729 lines — central agentic loop orchestrator)

---

## Core Philosophy

**"Lossless before lossy. Local before global."**

Context is a scarce resource, not a buffer to truncate. Claude Code applies a 4-layer cascade that exhausts all non-lossy options before applying destructive compression — inspired by OS virtual memory paging (MemGPT concept).

**NOT:**
- Sliding window (uniform age-based deletion regardless of importance)
- One-shot summarization (aggressive information loss too early)

**YES:**
- Graduated degradation: each layer does less information damage than the next
- Lossless layers always applied first; lossy layers only when token budget critical

---

## The 4 Layers

### Layer 1: HISTORY_SNIP (Lossless Deletion)

**What:** Delete messages not referenced in any subsequent turn.  
**When:** Applied first, continuously — no token threshold.  
**Information loss:** Zero. Unreferenced messages contribute nothing to future context by definition.  
**Mechanism:** Time-based heuristics detecting whether messages are referenced downstream.

**Non-obvious:** Current implementation uses simple heuristics, not attention-weighted importance scoring. Improvement opportunity: reference frequency scoring (how often a message is cited), explicit constraint detection (messages containing rules/requirements), tool results with config data.

### Layer 2: Microcompact (Cache-Level Hiding)

**What:** Conceal tokens at cache level without modifying actual content.  
**When:** Applied second, no explicit threshold.  
**Information loss:** None — content is still there, just hidden from effective token count.  
**Mechanism:** Leverages prompt caching so tokens don't count against context budget.

**Non-obvious:** This is a pure win — you get token budget relief without any content destruction. Apply before any lossy step.

### Layer 3: CONTEXT_COLLAPSE (Structured Archival)

**What:** Compress older conversational turns while preserving structural relationships.  
**When:** `tokenCount(conversation) > THRESHOLD_L3` (estimated ~70-80% of context window).  
**Information loss:** Lossy but structured — semantic meaning and conversation structure preserved, fine details removed.  
**Mechanism:** Compresses old turns while maintaining relationship graph between ideas.

### Layer 4: Autocompact (Full Compression)

**What:** Full summarization — emergency last resort.  
**When:** `tokenCount(conversation) > THRESHOLD_L4` (estimated ~90%+ of context window).  
**Information loss:** High — detailed conversation condensed into summary.  
**Mechanism:** Full LLM-based summarization of entire conversation history.

**Non-obvious:** After Layer 3 or 4, the model **does not know** it is operating on compressed context. It cannot signal uncertainty. This is an acknowledged unresolved tradeoff in the architecture.

---

## The Agentic Loop (context management in full flow)

```typescript
while (true) {
  // ① 4-layer context cascade
  conversation = historySnip(conversation);          // Layer 1: lossless
  conversation = microcompact(conversation);          // Layer 2: cache-hiding
  if (tokenCount(conversation) > THRESHOLD_L3) {
    conversation = contextCollapse(conversation);     // Layer 3: structured
  }
  if (tokenCount(conversation) > THRESHOLD_L4) {
    conversation = await autocompact(conversation);   // Layer 4: full summarize
  }

  // ② Pre-fetch memory + skills (CLAUDE.md, project memory)
  const memory = await prefetchMemory();

  // ③ Call Claude API (streaming)
  const stream = await callClaude(conversation, memory);

  // ④ While streaming: detect tool_use blocks → execute immediately
  for await (const event of stream) {
    if (event.type === 'tool_use') {
      // Read-only tools: run in parallel via RWLock
      // Write tools: exclusive lock, serial execution
      scheduleToolExecution(event);
    }
  }

  // ⑤ Append tool results → continue loop
  if (toolsExecuted) {
    conversation.push(...toolResults);
    continue;
  }

  // ⑥ No tools → return response → exit
  return finalResponse;
}
```

**Key:** Memory injection (step ②) happens AFTER context trimming (step ①). Memory is fresh; history is compressed.

---

## Memory File Loading

**CLAUDE.md and project memory are:**
- Pre-fetched in step ② of every loop iteration (not once at start)
- Injected fresh before every API call
- NOT subject to the 4-layer compression (they're re-loaded, not accumulated)

**Implication for your harness:** Don't store critical session constraints only in conversation history — they get compressed. Keep them in a memory file that's re-injected each turn.

---

## Tool Execution: Parallel Read + Exclusive Write

**Pattern:** Reader-writer lock (RWLock) on tool dispatch.

```typescript
interface ToolDefinition {
  name: string
  description: string
  inputSchema: ZodSchema        // Auto-generates JSON Schema
  call(): AsyncGenerator        // Streaming results
  isReadOnly(): boolean         // Determines lock type
  getPermissions(): Permission[]
  renderToolUse(): ReactComponent
  getToolUseSummary(): string   // For context compression summary
}

// Dispatch
if (tool.isReadOnly()) {
  rwlock.readLock(async () => tool.call(input));    // parallel
} else {
  rwlock.writeLock(async () => tool.call(input));   // exclusive
}
```

**Critical:** `getToolUseSummary()` produces compressed representation for context management. Every tool must implement this — it's what Layer 3 uses to compress tool results without losing structure.

**Caveat:** Read-only parallel execution accepts a small race window (e.g., user runs `git pull` in another terminal between reads). Model self-corrects on next turn. Deemed acceptable tradeoff.

---

## Feature Flag Architecture

**Two-tier system:**

| Tier | Mechanism | Purpose |
|------|-----------|---------|
| Compile-time | Bun dead code elimination | Security — unreleased features don't exist in binary |
| Runtime | GrowthBook/Statsig (disk-cached) | A/B testing, gradual rollout |

```javascript
// Compile-time (Bun)
const voiceModule = feature('VOICE_MODE')
  ? require('./voice/index.js')   // exists in binary
  : null;                          // physically deleted

// Runtime (Statsig, never blocks startup)
const enabled = checkStatsigFeatureGate_CACHED_MAY_BE_STALE('tengu_feature_name');
```

**Naming:** Internal features prefixed `tengu_` (天狗, Japanese mythical creature — internal codename).

---

## Key Files

| File | Lines | Role |
|------|-------|------|
| `src/query.ts` | ~1,729 | Entire agentic loop: context trimming, memory fetch, API call, tool dispatch, streaming |
| Context management | embedded in query.ts | 4-layer cascade, token counting, compression triggers |
| Memory pre-fetch | embedded in query.ts | CLAUDE.md + project memory loading |
| Tool dispatch | embedded in query.ts | RWLock-based parallel execution |

**Architecture note:** All logic in one 1,729-line file is a deliberate pragmatic choice — linear control flow, easy iteration, explicit step ordering. Tradeoff: merge contention at scale.

---

## Thresholds & Constants

| Constant | Value | Notes |
|----------|-------|-------|
| THRESHOLD_L3 | ~70-80% context window | Not publicly disclosed |
| THRESHOLD_L4 | ~90%+ context window | Not publicly disclosed |
| HISTORY_SNIP | No threshold | Applied continuously |
| Microcompact | No threshold | Applied continuously |
| BashTool timeout | 15 seconds | Commands blocking >15s auto-backgrounded |

---

## DO's

✅ **Apply cascade in order: lossless → lossy.** Never jump straight to summarization. Delete unreferenced messages first, cache-hide next, compress structure third, summarize last.

✅ **Pre-fetch memory fresh each turn.** Don't rely on session history for critical constraints — it gets compressed. Re-inject from file on every API call.

✅ **Implement `getToolUseSummary()` on every tool.** This is what structured compression (Layer 3) uses. Without it, compressors can only drop tool results entirely.

✅ **Use RWLock for tool execution.** Read-only tools run in parallel; write tools exclusive. Start executing read-only tools while model is still streaming — massive UX improvement.

✅ **Mark tools read-only carefully.** Only true if: no writes to disk, no network mutations, no shared state changes. Audit aggressively.

✅ **Measure with ablation testing.** ABLATION_BASELINE mode (disable everything) provides baseline. Quantify what each context management layer contributes — don't guess.

✅ **Use compile-time feature flags for security-sensitive features.** Dead code elimination = feature physically doesn't exist in binary.

---

## DON'Ts

❌ **Don't use a sliding window.** Uniform age-based deletion loses critical early constraints (system rules, user preferences, key decisions) at the same rate as irrelevant small talk.

❌ **Don't use single-pass summarization as your only strategy.** Too aggressive too early. Loses detail that could have been preserved with lossless deletion or cache-hiding first.

❌ **Don't wait for full model completion before executing tools.** Claude Code executes read-only tools DURING streaming. Serial wait-then-execute is the wrong pattern.

❌ **Don't use class inheritance for tool systems with >~20 tools.** No shared behavior between tool types → composition wins. `buildTool()` factory pattern + co-location of schema/execution/UI/permissions/summary is cleaner.

❌ **Don't allow sub-workers to spawn sub-workers.** Workers are flat — no hierarchical decomposition. Prevents resource explosion in agentic loops.

❌ **Don't expose compression state to the model.** Post-compression, model operates confidently on condensed info without awareness. This is the accepted tradeoff. If you need compression-awareness, inject an explicit signal into the context yourself.

❌ **Don't store critical constraints only in conversation history.** They will be compressed. Store in CLAUDE.md / memory file and re-inject each turn.

---

## Non-Obvious Design Decisions

**1. Compression blindness is accepted, not solved.**  
After Layer 3/4, model doesn't know what was condensed. Documentation explicitly calls this an open problem: "agents that can signal when they're operating on compressed context." If you need this, add it yourself — inject a `<compression-notice>` tag after Layers 3/4.

**2. HISTORY_SNIP is heuristic, not semantic.**  
Current: simple time-based "was this message referenced downstream?" Better (not implemented): attention-weighted importance scoring. Improvement opportunities: reference frequency, explicit constraint markers, tool result metadata.

**3. query.ts is intentionally monolithic.**  
1,729 lines is a feature, not a bug. Linear control flow = fast iteration. The tradeoff (merge contention at team scale) was accepted for shipping speed. Don't reflexively modularize it.

**4. `tengu_` prefix is internal codename for all feature flags.**  
If you see `tengu_` prefixed flags in Statsig/GrowthBook: these are internal Claude Code experiment flags.

**5. Functional tool factories over class hierarchy at scale.**  
At 40+ tools: `buildTool({ name, call, isReadOnly, getToolUseSummary, ... })` factory pattern outperforms inheritance. Each tool is self-contained — schema, execution, permissions, UI rendering, context summary all co-located.

---

## Minimal Implementation Blueprint

```typescript
// Token counting
function tokenCount(messages: Message[]): number {
  // Use your model provider's token counting API
  // Or estimate: ~4 chars per token for English text
}

// Layer 1: Lossless deletion
function historySnip(messages: Message[]): Message[] {
  const referenced = new Set<string>();
  for (const msg of messages) {
    // Mark any message IDs referenced in this message's content
    extractReferences(msg.content).forEach(id => referenced.add(id));
  }
  // Keep: messages that are referenced OR recent (last N turns)
  return messages.filter(m => referenced.has(m.id) || isRecent(m));
}

// Layer 2: Microcompact (leverage prompt caching)
// Handled by your API provider's cache_control markers — no action needed here

// Layer 3: Structured archival
async function contextCollapse(messages: Message[]): Promise<Message[]> {
  // Keep recent N messages intact
  const RECENT_KEEP = 10;
  const recent = messages.slice(-RECENT_KEEP);
  const older = messages.slice(0, -RECENT_KEEP);
  
  // Compress older turns using tool summaries
  const compressed = older.map(m => ({
    ...m,
    content: m.toolSummary ?? summarizeMessage(m)
  }));
  
  return [...compressed, ...recent];
}

// Layer 4: Autocompact (full summarization)
async function autocompact(messages: Message[]): Promise<Message[]> {
  const summary = await callLLM([{
    role: 'user',
    content: `Summarize this conversation preserving: key decisions, active constraints, tool results, user goals.\n\n${JSON.stringify(messages)}`
  }]);
  
  return [{
    role: 'assistant',
    content: `<compression-notice>Context compressed. Summary:\n${summary}</compression-notice>`
  }];
}

// Main agentic loop
async function agentLoop(conversation: Message[]) {
  while (true) {
    // ① 4-layer cascade
    conversation = historySnip(conversation);
    // microcompact: handled by cache_control markers on API call
    if (tokenCount(conversation) > THRESHOLD_L3) {
      conversation = await contextCollapse(conversation);
    }
    if (tokenCount(conversation) > THRESHOLD_L4) {
      conversation = await autocompact(conversation);
    }

    // ② Pre-fetch memory
    const memory = await loadMemoryFiles(['CLAUDE.md', 'project.md']);

    // ③ API call with memory injected
    const response = await callClaudeWithStreaming(conversation, memory);

    // ④ Execute tools during streaming
    const toolResults = await executeTools(response.toolUses, { useRWLock: true });

    if (toolResults.length > 0) {
      conversation.push(response.message, ...toolResults);
      continue;
    }

    return response.content;
  }
}
```

---

## Checklist for Implementation

- [ ] Layer 1 (HISTORY_SNIP): delete unreferenced messages before any lossy step
- [ ] Layer 2 (Microcompact): use `cache_control` markers on system prompt + last N messages
- [ ] Layer 3 (CONTEXT_COLLAPSE): trigger at ~75% token budget; compress old turns using tool summaries
- [ ] Layer 4 (Autocompact): trigger at ~90% token budget; full LLM summarization with `<compression-notice>` tag
- [ ] Memory files re-loaded fresh every loop iteration, injected post-trimming
- [ ] Every tool implements `getToolUseSummary()` for Layer 3 compression
- [ ] RWLock on tool dispatch: read-only tools parallel, write tools exclusive
- [ ] Read-only tools execute DURING streaming, not after
- [ ] Audit `isReadOnly()` on every tool for correctness
- [ ] No sub-worker spawning from workers (flat hierarchy)
- [ ] Critical constraints stored in memory files, not only in conversation history

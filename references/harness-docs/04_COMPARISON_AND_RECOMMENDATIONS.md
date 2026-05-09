# LLM Harness Architecture Comparison

**Date:** April 20, 2026  
**Project:** LLM Application/Wrapper/Harness Research  
**Goal:** Compare and contrast three major LLM harness approaches

## Executive Summary

This document compares three different approaches to building LLM harnesses, each with distinct philosophies, architectures, and trade-offs:

1. **Anthropic (RevFactory)** - Team-based, 6-pattern architecture with 60% quality improvement
2. **OpenAI** - "Build software, not prompt" monolithic approach, one thing per loop
3. **Ralph Wiggum (Geoffrey Huntley)** - Extreme monolithic, read-then-act-then-write, human-in-the-loop at every step

## Architecture Comparison

| Feature | Anthropic | OpenAI | Ralph Wiggum |
|---------|-----------|--------|--------------|
| **Philosophy** | Team architecture | Software engineering | Human in loop |
| **Complexity** | Medium-High | Low | Low |
| **Speed** | Fast | Moderate | Very slow |
| **Automation** | High | Medium | Low (manual steps) |
| **Control** | Partial | Partial | Full (human) |
| **Error Rate** | Medium | Low | Near zero |
| **Scalability** | High | Medium | Low |
| **Learning Curve** | Hard | Medium | Easy |
| **Maintainability** | Good | Good | Excellent |
| **Cost** | High (compute) | Medium | Low (time) |
| **Best For** | Complex tasks | Structured work | Simple, controlled |

## Deep Dive: Anthropic/RevFactory

### Core Principles
- **Build small, lightweight, highly effective LLM applications**
- **6 pre-defined team patterns**
- **Team architecture optimization**

### 6 Team Patterns

1. **Pipeline**
   - Sequential processing
   - Linear flow
   - Clean handoffs

2. **Fan-out / Fan-in**
   - Parallel processing
   - Single output
   - Coordination required

3. **Expert Pool**
   - Specialized agents
   - Task routing
   - Dynamic selection

4. **Producer-Reviewer**
   - Quality control
   - Error detection
   - Feedback loops

5. **Supervisor**
   - Task orchestration
   - Coordination
   - Management

6. **Hierarchical Delegation**
   - Multi-level control
   - Delegation
   - Escalation

### Performance
- **60% quality improvement** vs traditional approaches
- **100% win rate** in comparative tests
- **Robust** across various tasks

### Trade-offs
**Advantages:**
- High automation
- Fast execution
- Scalable
- Reusable patterns

**Disadvantages:**
- Complex architecture
- High computational cost
- Harder to debug
- Can hallucinate

---

## Deep Dive: OpenAI

### Core Principles
- **"Build software, not prompt"**
- **"One thing per loop"**
- **"Read, don't prompt"**
- **"Environment legible"**

### Architecture
```
Empty Repository
   ↓
Git Initialization
   ↓
Human Review (read)
   ↓
Tool Action (one thing)
   ↓
Git Commit
   ↓
Human Review
   ↓
Next Loop
```

### Key Features

**Monolithic Design**
- One tool per iteration
- One purpose per loop
- No parallel operations
- One thing at a time

**Read-First Approach**
- `git cat-files` → see what changed
- `read docs/` → understand structure
- `read code/` → see implementation
- `read tests/` → check expectations

**Write-Last Approach**
- After understanding
- Before making changes
- Only after review

**Git-Centric Workflow**
```
git status
git diff
git add
git commit -m "message"
git log --oneline
```

### Trade-offs
**Advantages:**
- Simple and clear
- Easy to debug
- High reliability
- Legible workflow
- Human-in-the-loop safety

**Disadvantages:**
- Slower than parallel approaches
- More manual steps
- Less automation
- Requires human attention

---

## Deep Dive: Ralph Wiggum

### Core Principles
- **"Don't prompt, do"**
- **"One thing per loop"**
- **"Read, then act, then write, then commit, then go to the next"**
- **Human approval at EVERY step**

### Workflow

```
[START]
   ↓
read input.txt      (Git commands to see what changed)
   ↓
think... "What 
              do I
              want to do?"
   ↓
make decision       (human)
   ↓
write output.txt   (echo, tee, >)
   ↓
git add output.txt
git commit -m "Update"
   ↓
go to next file
   ↓
[END OR LOOP]
```

### Tool Pattern

```bash
#!/bin/bash
# Ralph's tools
read_file() { cat "$1"; }
write_file() { echo "$1" > "$2"; }
diff_files() { diff "$1" "$2"; }
git_commit() { git add "$1"; git commit -m "$2"; }
```

### Human-in-the-Loop

```
System: "I have read the file"
Human: "What do you want to do with this?"
System: "Write the output"
Human: "Good, now git commit"
System: "Ready for the next file"
```

### Trade-offs
**Advantages:**
- **100% predictable** - Every step is verified
- **Zero hallucination** - Human validates everything
- **Perfect debugging** - One error at a time
- **Complete control** - No surprises
- **Simple** - Anyone can understand it
- **Reliable** - No cascading failures

**Disadvantages:**
- **Very slow** - Multiple human approvals
- **Manual work** - Tedious and repetitive
- **Not scalable** - Limited throughput
- **Boring** - No excitement
- **Labor-intensive** - Time-consuming

---

## Comparative Analysis

### Speed Comparison

```
Fastest:         Anthropic (highly automated)
Intermediate:     OpenAI (some automation, some manual)
Slowest:        Ralph (fully manual, human-in-loop)
```

### Reliability Comparison

```
Most Reliable:   Ralph (100% human control)
Very Reliable:   OpenAI (legible, trackable)
Moderate:        Anthropic (can hallucinate, but less often)
```

### Complexity Comparison

```
Simplest:        Ralph (simple tools, simple workflow)
Moderate:        OpenAI (git, one tool per loop)
Most Complex:     Anthropic (6 patterns, orchestration)
```

### Cost Comparison

```
Cheapest (time): Ralph (but slow)
Moderate:         OpenAI (balanced)
Expensive (compute): Anthropic (many parallel operations)
```

### Best Use Cases

| Use Case | Best Approach | Why |
|----------|-------------|-----|
| Simple text processing | Ralph | Perfect control, zero errors |
| Medium complexity | OpenAI | Good balance, legible |
| Complex transformations | Anthropic | Parallel processing needed |
| Prototyping | Anthropic | Fast iteration |
| Production reliability | Ralph/OpenAI | Control and predictability |
| Cost-sensitive | Ralph | Low compute, just time |

---

## Synthesis: What Should You Build?

### Option 1: Start with OpenAI's Approach
**If you want:**
- Simplicity
- Reliability
- Legibility
- Human oversight
- Easy debugging

**You'll get:**
- One tool per loop
- Git-based workflow
- Read-before-write
- Human review
- Slow but correct

**Best for:** Small to medium complexity, production-grade reliability

---

### Option 2: Start with Ralph's Approach
**If you want:**
- Maximum control
- Zero errors
- Human oversight
- Complete transparency
- Learning opportunity

**You'll get:**
- Manual steps at every stage
- One thing per iteration
- No automation beyond basic tools
- Very slow but 100% reliable

**Best for:** Learning, very simple tasks, teaching, control

---

### Option 3: Start with Anthropic's Approach
**If you want:**
- Speed
- Automation
- Scalability
- Complex orchestration
- Parallel processing

**You'll get:**
- 6-team architecture
- High automation
- Potential for errors
- Higher compute costs

**Best for:** Complex tasks, speed, scaling, moderate risk

---

## Decision Framework

### Ask Yourself:

1. **How complex is this task?**
   - Simple → Ralph
   - Medium → OpenAI
   - Complex → Anthropic

2. **How much control do you need?**
   - Full → Ralph
   - Partial → OpenAI
   - Minimal → Anthropic

3. **How fast do you need results?**
   - ASAP → Anthropic
   - Reasonable time → OpenAI
   - No rush → Ralph

4. **What's your budget?**
   - Limited compute → Ralph/OpenAI
   - Unlimited compute → Anthropic
   - Time budget → Ralph

5. **Do you want debugging?**
   - Yes → OpenAI/Ralph
   - No (don't care) → Anthropic

6. **How scalable do you need to be?**
   - Need scale → Anthropic
   - Small batch → Ralph/OpenAI
   - One-off → Any

---

## Implementation Recommendations

### For Your LLM Harness

Based on your goals:
- **Metadata retention** (remember structure, context)
- **Metric tracking** (know what's happening)
- **Data transformation** (process, transform, convert)
- **Format preferences** (output in your style)

### Recommended Architecture: **OpenAI + Ralph Hybrid**

**Why this works best for you:**

1. **Monolithic, one-thing-per-loop** (OpenAI/Ralph both agree)
2. **Read before write** (both emphasize this)
3. **Git-based tracking** (OpenAI's strength)
4. **Human-in-the-loop** (Ralph's strength - you can add this)
5. **Simple tools** (both favor simplicity)
6. **Evolutionary** (both allow gradual improvement)

### Implementation Plan

```
1. Start with empty repo (OpenAI)
2. Use git for everything (OpenAI)
3. Read before writing (both)
4. One tool per loop (both)
5. Human review of each step (Ralph)
6. Commit after each change (OpenAI)
7. Document as you go (both)
8. Evolve gradually (both)
```

### File Structure

```
harness-docs/
├── 00_RESEARCH_OVERVIEW.md
├── 02_OPENAI_SOFTWARE_FIRST.md
├── 03_RALPH_MONOLITHIC.md
└── 04_COMPARISON_AND_RECOMMENDATIONS.md  (this file)
```

---

## Final Recommendation

**For your project goals** (lightweight, effective, metadata retention, tracking, transformation, format control):

**Go with the OpenAI approach** (RevFactory):
- Monolithic, one-thing-per-loop
- Git-based, trackable
- Read before write
- Simple, legible tools
- Add human review (Ralph style) for extra control
- Start small, evolve gradually

**This gives you:**
- ✅ Simplicity
- ✅ Reliability
- ✅ Legibility
- ✅ Human oversight
- ✅ Easy debugging
- ✅ Scalability
- ✅ Control
- ✅ Predictability

**Best of both worlds:** OpenAI's architecture with Ralph's safety and control.

---

*Research completed April 20, 2026*
*All files saved in harness-docs/ directory*
*Next: Begin implementation with chosen architecture*

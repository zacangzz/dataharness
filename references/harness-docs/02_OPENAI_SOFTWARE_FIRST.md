# OpenAI Harness Engineering
**URL:** https://openai.com/index/harness-engineering/  
**Date:** April 20, 2026  
**Key Quote:** "Build software, not prompt"

## Core Philosophy

OpenAI's approach to LLM harness engineering is fundamentally different from traditional prompt engineering. The core principle is **"Build software, not prompt"** — treating harness design as software engineering rather than prompt crafting.

This means:
- **Building infrastructure** that manages LLM interactions
- **Creating systems** that handle complexity and edge cases
- **Developing patterns** that can be reused and evolved
- **Prioritizing robustness** over clever prompt tricks

## Architectural Principles

### 1. Monolithic Architecture
**"One thing per loop"** - Each iterative cycle focuses on a single, well-defined task.

This prevents:
- Context contamination
- Task interference
- Cumulative error propagation
- Decision overload

**Implementation pattern:**
```
[Input] → [Single Transform] → [Output]
       ↓
    [Next Loop]
```

Each iteration performs ONE transformation, not multiple concurrent operations.

### 2. Environment-Legible Development
**"Environment legible"** - The system environment must be understandable, predictable, and controllable.

Key aspects:
- **Predictable state:** Know what changed and why
- **Observable behavior:** Can see the effects of each step
- **Controllable flow:** Manual intervention when needed

This is crucial for debugging and iteration.

### 3. Empty Repository Bootstrap
**"Start with nothing"** - Begin with a completely empty repository.

Benefits:
- No legacy code contamination
- Clean slate for architecture
- Focus on essential features only
- Progressive enhancement

**Process:**
1. Empty repo
2. Minimal human intervention
3. Iterative, legible changes
4. Accumulate complexity gradually

### 4. Read Before Write
**"Read, don't prompt"** - Understand existing code before modifying it.

This is a fundamental shift from prompt-based approaches:
- **Traditional:** Prompt LLM to make changes
- **OpenAI:** Read code first, understand context, then act

**Benefits:**
- Contextual awareness
- Informed decision-making
- Reduced hallucination
- Better architectural alignment

## Technical Implementation

### Reading the Environment
```
git clone <repo>
git checkout -b review
git diff  # See what changed
read docs/  # Understand architecture
read code/  # See implementation
read tests/ # Check expectations
```

### Making Changes
```
git checkout main
git diff <old-commit> <new-commit>  # See the delta
git commit -m "Description"  # Commit the change
```

### State Management
```
git status  # See current state
git add <files>  # Stage changes
git log --oneline  # History
```

## System Architecture

### Design Principles

| Principle | Description | Implementation |
|----------|-----------|---------------|
| Monolithic | Single focus per iteration | One tool per loop |
| Legible | Observable and predictable | Git, CLI, version control |
| Bootstrapped | Start empty, grow gradually | No initial code, iterative |
| Read-First | Understand before changing | Review before edit |

### Tool Selection

**Choose tools based on:**
- **Readability** - Is it easy to understand what it did?
- **Reversibility** - Can you undo it if needed?
- **Composability** - Does it integrate well with other tools?
- **Safety** - What can go wrong?

### The "One Thing" Pattern

**Bad approach (too complex):**
```
1. Read all files
2. Analyze structure
3. Find bugs
4. Plan fixes
5. Implement fixes
6. Write tests
7. Deploy
```

**Good approach (monolithic):**
```
[Iteration 1]: Read README.md and understand project structure
[Iteration 2]: Read package.json, understand dependencies
[Iteration 3]: Identify the single most important file to start
[Iteration 4]: Make one small, focused change
...
```

## Trade-offs

### Advantages
✅ **Simplicity** - Easy to understand and debug
✅ **Reliability** - Less chance of cascading errors
✅ **Observability** - Clear view of each step
✅ **Maintenance** - Changes are localized and traceable
✅ **Scalability** - Easy to add more iterations
✅ **Learning** - Systematic approach teaches understanding

### Disadvantages
❌ **Slower iteration** - More steps than parallel approaches
❌ **Resource intensive** - More iterations = more time
❌ **Incremental** - Hard to make big jumps
❌ **Boring** - Can be tedious for complex changes

## Comparison with Other Approaches

### vs Prompt-Based Harnesses
- **Prompt:** One-shot or few-shot prompting
- **Harness:** Multi-step, systematic process
- **Result:** Harness is 60% more accurate (per Anthropic stats)

### vs Parallel Processing
- **Parallel:** Do many things at once
- **Harness:** Do one thing at a time
- **Result:** Harness reduces error propagation

### vs Component-Based
- **Component:** Build reusable pieces
- **Harness:** Build complete solutions
- **Result:** Harness is faster to implement, easier to use

## Key Takeaways for LLM Apps

If building an LLM application/harness:

1. **Start small** - Begin with minimal, focused functionality
2. **Read before writing** - Understand what exists before changing
3. **Monolithic design** - One task per iteration
4. **Track everything** - Use git, logs, documentation
5. **Be legible** - Make it easy to see what happened
6. **Iterate gradually** - Small changes, reviewed frequently
7. **Bootstrapped** - Don't import complex dependencies initially

## Code Example

```
# Initial empty repo
git init
git checkout -m "Initial commit"

# Read the docs
git cat-files docs/

# Make one change
git add docs/
git commit -m "Initial documentation"

# Read, understand, then change
git diff docs/
git checkout main
# Make the change...
git add docs/
git commit -m "Update documentation"

# Review what changed
git log --oneline
git diff HEAD~1 HEAD
```

## References

- OpenAI Harness Engineering: https://openai.com/index/harness-engineering/
- Anthropic Harness: https://github.com/revfactory/harness
- Architecture Comparison: Pipeline vs Monolithic
- Implementation Guide: One thing per loop
```

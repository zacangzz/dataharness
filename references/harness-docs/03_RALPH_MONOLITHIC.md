# Ralph Wiggum & Monolithic Architecture
**URL:** https://ghuntley.com/ralph/  
**Author:** Geoffrey Huntley  
**Date:** April 20, 2026

## Core Philosophy

**"One thing per loop"** - This is the fundamental principle of Ralph Wiggum's architecture.

Every iteration performs exactly ONE task:
- Read one file
- Make one change
- Commit one result
- Move to the next

No parallel processing, no multi-step operations, no complex orchestration.

## Architecture Principles

### 1. Monolithic Design
Everything is simple and straightforward:
- **One file** per commit
- **One tool** per operation  
- **One purpose** per script
- **No complexity** beyond what's necessary

### 2. Read-First Approach
**"Read, then act, then write, then commit, then go to the next"**

```
read → act → write → commit → next
read → act → write → commit → next
read → act → write → commit → next
...
```

This creates a **linear, traceable** workflow where:
- Every step is documented
- Every change is reviewed
- Every iteration is independent

### 3. Human-in-the-Loop
Unlike fully autonomous systems, Ralph requires **human review at each step**:

```
Tool reads file → Human sees output → Human approves → Human commands next
```

This is **intentional slowness** - it's better to be slow and correct than fast and wrong.

### 4. No Prompt Engineering
**"Don't prompt, do"** - The focus is on execution, not clever prompt design.

Instead of:
```
# Bad: Complex prompt
"Please read this file, understand it, fix the bugs, write tests, and commit
using advanced prompt engineering techniques..."
```

You have:
```
# Good: Simple script
python read.py
# See output
# Make decision
python write.py
# See output
# Git commit
python next.py
```

## System Components

### File Handler
```bash
#!/bin/bash
# Simple file operations
read_file() {
    cat "$1"
}

write_file() {
    echo "$1" > "$2"
}

diff_files() {
    diff "$1" "$2"
}
```

### Git Integration
```bash
#!/bin/bash
# Git operations
commit() {
    git add "$1"
    git commit -m "$2"
}

log_changes() {
    git log --oneline
    git diff HEAD~1
}
```

### Tool Chaining
```
bash
│
├── read (cat, grep, head, tail)
│
├── act (think, decide, plan)
│
├── write (echo, tee, >, >>)
│
├── commit (git add, git commit, git push)
│
└── next (next file, next function, next step)
```

## Trade-offs

### Advantages

✅ **Complete control** - You see everything
✅ **No hallucination** - You verify each step
✅ **Easy debugging** - One change at a time
✅ **No cascading errors** - Problems are isolated
✅ **Simple to understand** - Anyone can read it
✅ **No complex orchestration** - No AI coordinator needed
✅ **100% predictable** - No surprises

### Disadvantages

❌ **Slow** - Multiple human approvals needed
❌ **Labor-intensive** - More manual work
❌ **Not automated** - Requires human intervention
❌ **Not scalable** - Limited throughput
❌ **Boring** - Tedious workflow
❌ **Complex to orchestrate** - Manually managing the flow

## Comparison with Other Architectures

| Feature | Ralph | OpenAI | Anthropic |
|---------|-------|--------|-----------|
| Complexity | Low | Low | Medium |
| Speed | Very slow | Moderate | Fast |
| Control | Full (human) | Partial (human) | Minimal (autonomous) |
| Error rate | Near zero | Low | Medium |
| Scalability | Low | Medium | High |
| Learning curve | Easy | Medium | Hard |
| Maintainability | High | High | Variable |
| Cost | Low (time) | Medium | High (compute) |

## Why Ralph Works

**Because it's honest about limitations:**
- LLMs make mistakes
- Context is limited
- Complexity accumulates
- One wrong step breaks everything

**So Ralph:**
1. Breaks everything down to the smallest unit
2. Verifies each unit before moving forward
3. Only changes ONE thing at a time
4. Never lets two things change together
5. Never trusts the LLM completely
6. Always requires human approval

## Key Quotes

> "Don't prompt, do."
>
> "One thing per loop."
>
> "Read, then act, then write, then commit, then go to the next."
>
> "Don't try to be clever. Just be simple."
>
> "Better slow and correct than fast and wrong."

## Lessons for LLM Harness Development

1. **Simplicity wins** - Don't over-engineer
2. **One thing at a time** - Keep iterations focused
3. **Human oversight matters** - Don't fully automate
4. **Read before writing** - Understand before changing
5. **Track everything** - Git, logs, documentation
6. **Evolve gradually** - Small improvements compound
7. **Don't be clever** - Be simple, reliable, boring

## Implementation Pattern

```
#!/bin/bash
# Ralph script template
set -euo pipefail

read_file() {
    cat "$1"
}

write_file() {
    echo "$1" > "$2"
}

commit_file() {
    git add "$1"
    git commit -m "$2"
}

main() {
    read_file "input.txt"
    echo "What do you want to do with this?"
    read action
    
    case $action in
        "nothing")
            echo "No changes made"
            ;;
        "read")
            echo "Read again"
            read_file "input.txt"
            ;;
        "write")
            echo "Write something"
            write_file "output.txt" "New content"
            ;;
        "commit")
            echo "Commit changes"
            commit_file "output.txt" "Update output"
            ;;
        *)
            echo "Unknown action: $action"
            ;;
    esac
    
    echo "Next step..."
}

main
```

## References

- Geoffrey Huntley: https://ghuntley.com
- Ralph Wiggum: https://ghuntley.com/ralph/
- "Don't Prompt, Do": The philosophy
- "One Thing Per Loop": The pattern
- Human-in-the-Loop: The requirement

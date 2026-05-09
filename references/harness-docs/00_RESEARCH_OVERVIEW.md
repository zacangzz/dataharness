# Harness Research Overview
**Date:** April 20, 2026  
**Session:** Continuation of LLM Harness Research

## Executive Summary

This document summarizes the research into three major LLM harness architectures:
1. **Anthropic's Harness Design** - Team-based architecture with 6 patterns
2. **OpenAI's Harness Engineering** - "Build software, not prompt" philosophy  
3. **RevFactory's Harness** - 6-phase workflow with 60% quality improvement

## Research Links

- OpenAI: https://openai.com/index/harness-engineering/
- Geoffrey Huntley (Ralph): https://ghuntley.com/ralph/
- RevFactory: https://github.com/revfactory/harness

## Key Findings

### 1. Anthropic Team-Based Harness
- **Core Philosophy:** "Build small, lightweight, and highly effective LLM applications/wrapper/harness"
- **Structure:** Uses 6 pre-defined team architecture patterns
  1. Pipeline
  2. Fan-out/Fan-in
  3. Expert Pool
  4. Producer-Reviewer
  5. Supervisor
  6. Hierarchical Delegation
- **Goal:** Enhance LLM performance through structured pre-configuration
- **Evidence:** 60% quality improvement in tests

### 2. OpenAI Approach
- **Core Philosophy:** "Build software, not prompt"
- **Structure:** Monolithic, one-thing-per-loop design
- **Environment:** Empty repository, bootstrap with minimal human code
- **Reading:** "Read, don't prompt"
- **Tuning:** Comprehensive system tuning rather than prompt tuning
- **Debugging:** CLI+Terminal debugging pattern
- **Result:** More reliable, maintainable systems

### 3. RevFactory Harness
- **Type:** Team-Architecture Factory for Claude Code
- **Structure:** 6-phase workflow
  1. Domain Analysis
  2. Team Architecture Design
  3. Agent Definition Generation
  4. Skill Generation
  5. Integration & Orchestration
  6. Validation & Testing
- **Performance:** +60% average quality, 100% win rate
- **Evolution:** Harness evolution mechanism for continuous improvement
- **Companion:** Archon for runtime configurations

## Research Directory Structure
```
harness-docs/
├── 00_RESEARCH_OVERVIEW.md       (this file)
├── 01_ANTHROPIC_TEAM_ARCH.md    (Anthropic harness patterns)
├── 02_OPENAI_SOFTWARE_FIRST.md  (OpenAI philosophy)
├── 03_REVFACTORY_6_PHASE.md     (RevFactory workflow)
├── 04_GITHUB_REPO.md            (RevFactory repository)
└── INDEX.md                       (cross-reference index)
```

## Next Steps
- Continue reading OpenAI documentation
- Analyze Ralph Wiggum article completely
- Document RevFactory repository structure
- Compare and contrast approaches
- Create implementation templates

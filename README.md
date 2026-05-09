# DataHarness: A fully local lightweight portable app using LLMs to query private & sensitive data for Data Analytics / Data Science / Reporting

Disclaimer: This app is built with the use of Claude Code, Codex, Gemmini, and OpenCode (OpenRouter). It has been iterated for over 2 months, and is currently still undergoing further iterations. This is actually the 3rd iteration, the 1st one was never published. The 2nd one was abandoned. The current iteration is a fully custom ground up application meant to emulate the best practices of an LLM Harness.

## Purpose

Issue with risk averse companies: extremely slow and overzealous protection against advancement in AI and other technologies. This app is my solution to that. It uses the fully permissive open source Gemma 4 E4B instruction trained model, to prop up a querying engine to help speed up certain 'analytics' related queries that are typicallly asked of the HR analytics teams. Simple queries, like headcount, attrition, etc. that can now be at the fingertips of HRBPs and Business Leaders.

## Learning Points

- Initial design was to have a fancy UI/UX, using Electron. However, that quickly became extremely difficult to manage beause Electron is not a small package to manage. Packaging an Electron app came with it's own set of issues and baggages and so after doing that for a few iterations, I abandoned it entirely and restarted with the current repo.
With previous mistake in mind, I decided to go with Tauri. It is significantly lighter and faster, and the initial development went smoothly. However, debugging became a problem too and the bagging was just not worth it. It is rust-based and I must admit my Typescript is not good, reading and directing LLM actions started to take up too much of an overhead, so I decided to finally go with just a simple CLI app.
- In addition to the UI issue with GUI apps, the problem is also that the initial design utilised FastAPI and setup a localhost which was used to pass data between the 'backend' and 'frontend' layer. This was problematic and I quickly learnt that it there is no point doing something like this when simpler and better approaches work. After all, this is intended to be a fully local app, there is no reason to build any API which only complicates the code and make things harder to debug.
- On the Inference side, the initial local LLM tested was a much smaller and weaker Qwen model, in order to make up for its weakness, I had to design a custom pipeline around the LLM to actually put in hard limits on what the LLM can do. This resulted in an app that is very much no different to a standard chatbot, or worse. It completely negates the whole point of having an LLM in the first place. It's to actually think and make the decisions and help the user process the data efficiently and effectively. That's is why I embarked on a full rewrite, transitioning the app from a custom pipeline into a smolagents pipeline.
- CLI - transitioned from Clicker to Typer, then moved from Rich to prompt_toolkit. Realise that even choose the right CLI engine is also important, it needs to be something that actually fits the project goals.

## Notes about AI Vibe Coding

- Context management so important, compact regularly and point to instructions clearly. Always Plan, save plan, then compact, then execute. Review plans to ensure that direction is where you want to go.
- /superpowers skill really helps to provide structure especially once the codebase becomes big enough. Always look to keep edits small and manageable if possible, if not, let the planing process break implementation plans to much smaller phased plans that can be run bit by bit, otherwise the LLM may get lost in a huge plan. Also important for saving tokens and managing context.
- always start small and slowly iterate up. Breakdown functions and features into much smaller set. Go smaller than you think you need to, this way you can really clearly direct the development into the structure you want.
- Be clear about the structure you want!!! If you don't know what you want, the decision will be made for you and you will end up confused and regretting your non-decisions.
- I've restarted the project 3 times, each time wasting days of work before hitting a wall. It's important to know when to stop, consolidate all the learning points and then retrying with a different strategy.
- Vibe Coding is so last year, we do Spec Driven Development now!

## About LLMs

Context Management is a serious issue, not properly managing it will bust token budget. Not setting a proper budget will cause over heating of RAM.
Thinking costs more tokens.
Tool calls are also consuming tokens - more tools = more schema to load = more tokens consumed
Next Steps:

Add in data onboarding steps
Figure out better LLM params stop overthinking,
Why is pipeline.py full of regex???!!!

## References
https://hackernoon.com/cielara-code-just-beat-claude-code-and-codex-at-the-hardest-part-of-agent-work
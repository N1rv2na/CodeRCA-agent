# Domain Docs

CodeRCA is a single-context repository. Engineering agents must read the domain glossary and relevant ADRs before changing the design or implementation.

## Sources

- `CONTEXT.md` is the canonical ubiquitous-language glossary.
- `docs/adr/` contains accepted system-wide architecture decisions.

## Rules

- Use glossary terms in issue titles, specifications, implementation names, tests, and reports.
- Do not replace a canonical term with a synonym listed under `_Avoid_`.
- If a required concept is missing or ambiguous, resolve it through domain modeling before adding new vocabulary.
- Surface conflicts with accepted ADRs explicitly; do not silently override them.

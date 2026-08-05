# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues at `N1rv2na/CodeRCA-agent`. Use the `gh` CLI for issue operations and infer the repository from the configured Git remote.

## Conventions

- Create an issue with `gh issue create`.
- Read an issue and its discussion with `gh issue view <number> --comments`.
- List work with `gh issue list`, filtering by state and labels as needed.
- Add or remove workflow labels with `gh issue edit`.
- Close completed or rejected work with `gh issue close` and a concise resolution comment.

## Publishing from skills

When a skill says to publish a specification, ticket, or decision to the issue tracker, create a GitHub issue in this repository and apply the configured triage label.

## Pull requests as a request surface

**PRs as a request surface: no.** Pull requests are not treated as incoming feature requests or triage items.

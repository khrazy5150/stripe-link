# CLAUDE.md

## Purpose

This repository contains two related codebases:

-   **stripe-cart** --- the legacy implementation and behavioral
    reference.
-   **stripe-link** --- the new JSON-first implementation and the only
    codebase that should be actively evolved.

Your goal is to migrate functionality from **stripe-cart** into
**stripe-link** while preserving user-visible behavior and improving the
architecture.

------------------------------------------------------------------------

## Execution Workflow

Before writing or modifying code:

1.  Inspect both repositories.
2.  Learn the architecture of `stripe-link`.
3.  Identify the equivalent implementation in `stripe-cart`.
4.  Search `stripe-link` for existing implementations before creating
    anything new.
5.  Form a migration plan.
6.  Implement the smallest practical change.
7.  Verify behavioral parity.
8.  Continue to the next feature.

Do not skip the repository discovery phase.

------------------------------------------------------------------------

## Primary Priorities

1.  Preserve user-visible behavior.
2.  Follow the architecture of `stripe-link`.
3.  Reuse existing implementations.
4.  Keep changes incremental.
5.  Leave the repository cleaner than you found it.

------------------------------------------------------------------------

## Repository Rules

-   Search before creating.
-   Extend before replacing.
-   Refactor before rewriting.
-   Keep business logic out of Vue components.
-   Presentation components should remain presentation-focused.
-   Avoid duplicate implementations.
-   Remove temporary migration code when it is no longer required.

------------------------------------------------------------------------

## Decision Priority

When guidance conflicts, use this order:

1.  Existing `stripe-link` architecture
2.  The PRD
3.  `stripe-cart` behavior
4.  Engineering best practices

------------------------------------------------------------------------

## Clarification Policy

Do **not** stop for minor implementation details.

Continue working when the decision only affects:

-   formatting
-   naming
-   coding style
-   internal implementation details

Stop and ask for clarification when multiple reasonable implementations
would materially affect:

-   architecture
-   public APIs
-   data models
-   deployment
-   security
-   migration strategy
-   future extensibility
-   user-visible behavior

When asking a question:

-   explain the alternatives
-   explain the trade-offs
-   recommend the option you believe best fits the architecture

------------------------------------------------------------------------

## Migration Philosophy

Treat `stripe-cart` as the behavioral specification.

Treat `stripe-link` as the architectural specification.

The objective is **functional equivalence, not structural equivalence**.

Do not copy the legacy architecture simply because it exists.

Instead:

-   preserve behavior
-   modernize implementation
-   maintain clean separation of concerns
-   prefer JSON-first design

------------------------------------------------------------------------

## Definition of Done

A migration is complete when:

-   user-visible behavior matches the legacy implementation unless
    explicitly changed
-   no known regressions remain
-   existing code has been reused where practical
-   duplicate migration code has been removed
-   the implementation naturally fits the architecture of `stripe-link`

------------------------------------------------------------------------

## General Expectations

Think before editing.

Read more than you write.

Make small, reviewable changes.

When in doubt about an important architectural decision, ask instead of
guessing.
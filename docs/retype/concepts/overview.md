---
label: Overview
order: 100
---

# Core concepts

VySol is built around a small set of ideas that should remain useful even as individual implementations change.

## Source grounding

Information from source material should remain traceable and distinguishable from conclusions produced by the system.

A useful world model needs to know whether something came from the source, was inferred from source-supported facts, was generated to fill an unspecified part of the world, or happened later during simulation.

## Structured world context

A fictional world is more than a collection of passages. Characters, locations, relationships, objects, events, knowledge, and story flow affect one another.

VySol uses structured context so retrieval and simulation can reason across those connections instead of relying only on text similarity.

## Character perspective

The same world can look different from different characters' perspectives.

What a character says or does should be constrained by what that character could perceive, know, remember, infer, or believe at that point in time.

## Memory and continuity

Worlds change. Characters learn, forget, move, form relationships, make decisions, and experience events.

VySol aims to preserve enough temporal and causal context for later behavior to remain consistent with what came before.

## Simulation

Simulation builds on the world model rather than replacing it. New events can alter the state of the world, while the system keeps sourced history and later simulated history understandable as different kinds of information.

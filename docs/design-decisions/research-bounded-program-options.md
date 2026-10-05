# Design Decision: Research-Bounded Program Options

A program generator has to turn research findings into concrete choices a
user can make — "how much volume do I want?", "how many days a week?" —
and into mechanical rules that build a program from cited numbers. Both
are places where a product can quietly say more than the research does.
This document covers how the options and rules are tied to the evidence,
and what changed when they weren't.

## Cited claims, mechanical consequences, cited rules

Research makes claims at a particular level: weekly sets per muscle, not
sets for one exercise in one session. So the app generates and cites the
claim at the level the research makes it, then applies it mechanically —
a muscle's weekly sets are split evenly across its training sessions, then
across that session's exercises (at most three sets per exercise for
hypertrophy). The mechanical step isn't a research claim, but the
*reasons* for it are, so each rule is stated as one fixed claim and checked
by the same judge as everything else — "spreading weekly sets evenly
across sessions keeps per-session volume moderate, because additional sets
within one session give diminishing returns." Only excerpts the judge
accepts are shown as the rule's sources, and a rule nothing supports says
so instead of pretending. Conventions with no research behind them (half
credit for secondary muscles, the cap on exercises per day) are labeled as
conventions.

## Volume options: bound to efficiency tiers

Users pick **Minimalist**, **Moderate (recommended)** or **Higher volume**.
Originally that was free-form guidance to the generator ("choose the
lowest effective volume", "toward the high end"). Measuring what it
produced exposed two problems:

- The preference decided the band, but loosely: hypertrophy came out 3–12
  sets for minimal, 12–24 for moderate, and ~31 for high — that last one
  being the point past which one meta-analysis could *detect* no further
  benefit, a boundary of the data rather than a recommended dose (and the
  judge rejected it about half the time). Left unguided, "moderate" aimed
  for it too.
- Values differed between muscles for no research reason — 12 sets for
  side delts, 24 for quads — because each muscle's retrieval happened to
  surface different excerpts.

The fix ties each option to the efficiency tiers from the largest volume
meta-analysis in the corpus (Pelland et al. 2025), which report how many
additional weekly sets it takes to produce another detectable gain:

| Option | Hypertrophy (weekly sets) | Strength (weekly sets) |
|---|---|---|
| Minimalist | 5–10 (higher-efficiency tier) | 1–2 (minimum dose, higher efficiency) |
| Moderate (recommended) | 11–14 (intermediate) | 3 (intermediate) |
| Higher volume | 15–18 (intermediate) | 4 (intermediate) |

The generator can't produce a value outside the band (the output schema
only allows the band's numbers); it still picks the value and cites it, and
the judge still checks it. Every option stays inside the tiers where added
sets still pay off efficiently. For strength, the tiers end at four sets —
past that, the meta-analysis reports additional sets "do not consistently
enhance strength gains" — so all three strength options stay inside them.
The tiers themselves are a cited rule, linked from the volume selector.

Naming was part of the decision. "Maximalist" was considered and dropped:
the highest option is the top of the *efficient* range, not maximal
volume, and the research supports going higher with smaller returns. A
name shouldn't promise what the setting doesn't do. "Recommended" marks
the app's sensible default, not a research finding — all three options are
inside efficient tiers; Minimalist gets the most growth per set, Higher
volume the most total growth.

## Frequency: a finding, not a number

For hypertrophy the app originally generated a recommended frequency per
muscle and showed it next to the user's plan — "research suggests 2x/week"
beside "you train it 3x/week". That reads as if 3x were too much, which no
evidence says. A literature check found no study showing three sessions a
week beat two when weekly sets are matched: a direct 2x-versus-3x trial
found similar growth (Lasevicius et al. 2019, ingested for this), 3x
versus 6x was similar (Saric et al. 2019), and a meta-analysis of 25
studies concluded frequency doesn't meaningfully affect growth when volume
is equated. The studies often cited for high frequency compare it against
training a muscle once a week, which is a different question.

So hypertrophy frequency is now presented as what the research actually
says, in two cited parts:

1. With weekly sets matched, no significant difference between training a
   muscle 2x and 3x a week has been shown.
2. More sessions still help at higher volumes, because gains within a
   single session diminish past roughly 11 sets for a muscle (Remmert et
   al. 2025) — spreading volume keeps every session productive.

The wizard's days-per-week choice became a frequency selector ("3x per
muscle · 6 days/week" — within a split the two map one-to-one), and each
muscle shows its frequency and resulting sets per session instead of a
competing number. Strength keeps a generated, cited frequency, because
there frequency does matter (roughly +3% strength per additional weekly
session in the same meta-analysis).

## Why bother

Every one of these is a case where the app could have been "mostly right"
and still mislead: an option name that overpromises, a recommended number
that implies an alternative is worse, a range boundary treated as a
target. The project's premise is that every number and every claim is
something the user can check against a source. The options a user picks
from are claims too.

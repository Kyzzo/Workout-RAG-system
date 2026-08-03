# Deployment and CI/CD

A lot of this work was genuine debugging rather than following a known
recipe — platform quirks, a monorepo problem that recurred across two
different platforms, and one real security-adjacent onboarding trap. That
debugging is the actually interesting part, more than the deploy steps
themselves.

## Making configuration environment-driven before deploying, not after

Before any deployment happened, every hardcoded local value — a database
connection string, a local API base URL, a CORS allow-list — was made
configurable via environment variables with local-development fallbacks,
so nothing would break in an environment where those defaults didn't
apply. Auditing for hardcoded assumptions deliberately, before deploying,
is cheaper than discovering them via a production crash.

## Services, not just "a deploy"

Modern platform-as-a-service tools generally treat a project as a
collection of cooperating services (a database, an API) rather than one
opaque deployment — wired together with reference variables that resolve
to another service's live configuration, so if one service's credentials
ever rotate, everything referencing them updates automatically instead of
needing manual copy-paste kept in sync by hand.

## The monorepo "root directory" problem, twice, on two different platforms

Both deployment platforms used here support connecting a single git
repository that contains more than one deployable application — and both
needed to be told explicitly which subdirectory to treat as the actual
build root, otherwise each one tried to build the entire repository and
failed immediately, since the relevant build files only exist inside a
subdirectory, not at the repo root.

Worth naming as a general, transferable concept rather than a
platform-specific quirk: "point the platform at the right subdirectory in
a monorepo" recurs across essentially every PaaS that supports connecting
a repository containing more than one app. Recognizing it immediately the
second time it appeared (on the second platform) came directly from having
debugged it once already on the first.

A related, subtler version of the same problem: a platform's *stored*
project configuration and *where a CLI command is actually invoked from*
are two separate things that need to agree. A command-line deploy run from
inside the application subdirectory, with the platform's root-directory
setting still pointed at that same subdirectory relative to the repo root,
applied the setting on top of the current directory — looking for a
nonexistent nested subdirectory and failing with a confusing path error.
Git-triggered deploys and CLI-invoked deploys can silently assume
different starting points for the same stored setting.

## A signup flow that defaults into a paid trial

Creating an account on one platform required first creating a "team," even
for solo use — a real, current requirement, not an assumption. During
that flow, the only options presented were trial tiers of a paid plan; a
free tier existed but wasn't visibly offered in that specific dialog, and
had to be selected afterward as an explicit downgrade in billing settings,
or the trial would convert to paid billing automatically once it ended. A
signup flow that defaults into a trial of the paid tier, with the free
tier only reachable as a post-creation downgrade, is a common shape worth
explicitly checking for on any new platform account rather than assuming
a default matches what was actually requested.

## An accidental duplicate resource, caught by verifying, not assuming

An auto-accept flag passed to a CLI linking command, with no existing
local link present, silently created a brand-new empty project instead of
prompting to link the already-existing one from an earlier manual setup
step. This was caught only by explicitly listing existing projects
afterward and noticing two where there should have been one — not from
any error message, since the command itself exited cleanly. The general
lesson: an auto-accept or auto-confirm flag skips *confirmation* prompts,
not *decision* prompts — if a tool has to choose between two different
outcomes with no existing state to disambiguate, an auto-accept flag can
silently pick the wrong one. Verifying with a listing command after any
CLI action that creates infrastructure catches this; trusting a clean exit
code doesn't.

## Client-side environment variables are compiled in at build time

The most confusing production bug of this stretch of work: the deployed
frontend kept trying to reach a local development URL, even though the
correct value was visibly set correctly in the platform's dashboard,
scoped to the right environment. The reason: the framework replaces
client-exposed environment variable references with their literal string
value *inside the compiled JavaScript bundle*, at build time — not read
dynamically when a page loads in the browser. If the variable wasn't
present, or wasn't finalized, at the exact moment a given build ran, the
code's fallback default got baked into that bundle permanently, and no
amount of changing the dashboard value afterward fixes an already-built
deployment. Only triggering an entirely fresh build picks up a changed
value.

The diagnostic path that found this: the browser's own error had no
detail, but the browser's network inspector showed the *exact* URL being
requested and confirmed it wasn't even attempting the right host;
re-setting the variable explicitly (to rule out a saved-wrong-value
theory) changed nothing; only an explicit fresh production build actually
picked up the corrected value. This is a common, transferable class of "I
already set that, why isn't it working" confusion any time a framework
bakes configuration into a build artifact rather than reading it at
runtime.

## CI and CD are separable, and were deliberately added in a specific order

Continuous integration (automatically running checks before code is
trusted) and continuous deployment (automatically shipping code once it's
ready) solve different problems and don't have to arrive together or in
either particular order. This project has continuous deployment without
continuous integration for a deliberate reason: there was no test suite
yet for a CI step to meaningfully run against. A CI workflow at that point
could only run shallow checks — does the code parse, does it type-check —
real, but thin, and specifically would not have caught a genuine
environment-configuration bug found later (see below) unless the
workflow's own environment happened to exactly mirror production's, which
it wouldn't by default.

Basic continuous deployment for a modern platform-as-a-service isn't a
file checked into the repository at all — it's a webhook subscription
configured on the *platform's* side: watch a given branch, and re-run the
already-known build/deploy process whenever a push arrives. Nothing to
write, unless custom build or test logic beyond what the platform
auto-detects is needed.

## A config existing is not the same as a config working

One platform's git integration turned out to already be connected from
the very first setup step — confirmed by attempting to connect it again
and having the platform report it was already connected, rather than
creating a new connection. But checking actual deployment history showed
every prior deployment had been triggered manually from the command line,
never automatically from a push — meaning the automatic trigger had never
actually fired, only the manual path had ever been used, despite the
connection technically existing the whole time.

A second, more specific version of the same lesson turned up wiring the
same kind of connection for the backend service: a platform's dashboard
can show a repository as "connected" while push events still never
reach it, because there are two different grants involved — a lighter
authorization grant (permission to query on a user's behalf) and full app
installation (which is what actually enables webhook delivery for push
events). A connection created through one path can end up authorized but
not installed, silently making automatic deploys never fire despite
looking configured. Fixing it required installing the platform's app for
real through GitHub's own settings, and then — because the platform's
stored connection record had gone stale, created before real access
existed — an explicit disconnect and reconnect to force it to
re-establish against the now-real installation. Confirmed fixed not by a
dashboard status field, but by triggering an actual push and checking that
a new deployment appeared with a timestamp genuinely after that push.

## Build success and runtime success are different claims

Once a genuine monorepo build issue was fixed, an automatically-triggered
build succeeded — and the container then crashed immediately on startup,
missing an API credential that existed in local configuration but had
never been added to the deployed environment's variables. This is a real,
common class of bug (environment parity — configuration existing in one
environment but not another) surfaced for free by finally exercising the
automated path for the first time. It's specifically a *runtime* failure,
not a build failure, because the client requiring that credential gets
constructed at module-import time rather than lazily on first use — a
platform reporting "build successful" says nothing about whether the
application can actually start. Any resource initialized at import time
(database connections, external API clients, configuration parsing) will
surface a missing-configuration problem as a startup crash rather than a
build failure — worth deliberately choosing whether a given resource
should fail loudly and immediately at startup, or lazily on first real
use. This project generally favors failing loudly at startup: better to
crash immediately and obviously than serve requests from a
half-configured application.

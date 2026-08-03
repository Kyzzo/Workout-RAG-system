# Building Auth and the Data Layer

Covers the foundation: Clerk-issued JWTs verified by FastAPI, the
SQLAlchemy modeling layer underneath it, and the CRUD API built on top —
including the version-drift and security issues found along the way.

## Verifying real library versions instead of trusting memory

A recurring pattern across this project: documentation and cached
knowledge of a library's API can lag behind what's actually installed.
Two concrete examples from wiring up authentication:

- The framework's middleware file convention had been renamed in the
  installed version, deprecating the old convention most tutorials still
  reference — confirmed by checking the framework's own source rather
  than assuming.
- The installed auth SDK's conditional-rendering components had been
  replaced between versions — the well-documented pattern no longer
  matched what the package actually exported. Confirmed by reading the
  installed package's own type definitions directly and finding the real,
  current API.

The general lesson, repeated enough times across this project to be worth
stating once clearly: a library's public API can drift between versions
even when the underlying concept stays the same. Checking the actual
installed package — not the commonly-documented pattern, not even
previously-written code against an older version of the same dependency —
is cheaper than debugging a wrong assumption later.

## Middleware-based vs. resource-based authorization checks

The initial approach used a central path-matcher deciding which routes
require authentication — one file, one rule, based on matching URL paths
against a list. This was deliberately migrated to a different pattern:
checking authorization directly on each protected resource instead of in
one shared config file.

The reason for the migration, not a style preference: the SDK's own
migration guide documents concrete, non-hypothetical risks with
path-matching-based protection — server functions can be invoked by
identifier rather than URL path, bypassing a path-based rule entirely; a
real, disclosed vulnerability resulted from mismatches between how a
matcher parses paths and how the framework actually resolves them; and
multiple framework-level bypasses have been publicly disclosed where a
request never reaches the matcher at all.

Moving the check onto the resource itself removes that whole class of
bug: protection lives with the thing it protects, so there's no separate
config file that can silently drift out of sync with real routes as the
app grows, and no code path that can reach a resource without the check
running — short of forgetting to write the check on a given page, which is
a much smaller, more visible mistake than a subtle path-matching gap. The
cost: every future protected page needs its own explicit check instead of
one shared rule — worth it while the protected surface is still small
rather than retrofitting later.

## Verifying a JWT without a shared secret

The backend verifies tokens issued by the auth provider without ever
holding a shared secret, using the provider's public JWKS endpoint
(derived from the public key already configured, rather than hardcoded
separately, so it can never drift out of sync with which environment —
dev or production — is actually configured). A library handles fetching
and caching the provider's public signing keys and matching the right one
by key ID; the actual RSA signature verification is entirely the
library's responsibility, never hand-rolled.

One check the library can't do generically: confirming the token's
"authorized party" claim matches this app's own known origin — an
app-specific CSRF-prevention check that has to be written manually,
since a generic JWT library has no way to know which origins a given
application trusts. Every verification failure — bad signature, expired
token, malformed input, wrong origin — returns the same generic
unauthorized response regardless of which specific check failed,
deliberately: telling a caller exactly why their token failed would hand
an attacker free information for probing the system.

## Authentication proves who; authorization proves what they can see

Verifying a token only proves who's calling — it says nothing about
whether they're allowed to see a *specific* resource. Every resource
lookup filters by both the resource ID and the requesting user's own ID.
Without that second condition, any authenticated user could view any
other user's data just by guessing or incrementing an ID in the URL — a
common vulnerability class (insecure direct object reference). Returning
a generic "not found" rather than "forbidden" for someone else's resource
is deliberate too — it avoids confirming to an unauthorized caller that a
given resource even exists.

## The ORM layer: what's a database constraint vs. a Python convenience

Two genuinely separate things get conflated easily when learning an ORM
for the first time, worth stating precisely: a foreign key is an actual
database-level constraint — a real column and a real rule Postgres
enforces, which is what stops an invalid reference from ever being
inserted. A relationship declaration on top of that is a pure
Python/ORM-level convenience — it's what lets related objects be navigated
as live Python attributes in both directions without hand-writing a join,
but it doesn't exist in the database at all. Keeping these mentally
distinct made every subsequent modeling decision easier to reason about.

Nullability and uniqueness were modeled explicitly per column based on
what's actually true about the data, not applied as a default: a "rest
days before this session" field is nullable specifically because the
first session in a rotation genuinely has nothing to be relative to; a
user's external identity field is unique because it's the actual identity
link tying a database row to a real authenticated account.

Sync database access (not async) was a deliberate stack choice, not an
oversight: this was a first real project working with an ORM, migrations,
and relational modeling — adding asynchronous concurrency concerns on top
of that at the same time would have compounded two separate learning
curves into one, rather than isolating them.

## Migrations, and diffing models against a live database

Rather than letting an ORM "sync" the database directly, every schema
change goes through a migration tool that diffs the ORM's model
definitions against the actual live database and generates the SQL needed
to reconcile them — necessary once real data exists (an in-place `ALTER
TABLE` rather than recreating a table from scratch), and it leaves a
permanent, ordered, replayable log of every schema change ever made, the
same way version control leaves a log of every code change.

## Deliberate, temporary simplifications, and why they were temporary

A hardcoded placeholder user ID stood in for real authentication during
the earliest CRUD development — not a shortcut left in by accident, but a
deliberate sequencing choice: prove the data and schema layer works in
isolation before adding a second, independent source of potential bugs
(real JWT verification) on top of it. Debugging two new systems at once is
harder than debugging one at a time. It was replaced with real
authenticated identity once the data layer was proven separately.

Several tables were read-only in the earliest version of the API — they
appeared nested inside a parent resource's response, but had no dedicated
creation endpoint yet, since full manual editing of deeply nested data
wasn't the current milestone. Test data for those tables was inserted
directly rather than through an API that didn't exist yet, a normal and
expected gap at that stage rather than an oversight.

## Avoiding the N+1 query problem on a deeply nested schema

Object-relational mappers load relationships lazily by default — accessing
a related collection fires a new query at that moment, not before. On a
schema nested four levels deep, naive serialization would mean one query
for the top-level resource, plus one for each level of children, plus one
per child at the next level down — dozens of round trips for a single API
response. The fix: explicitly eager-loading the entire relationship chain
via a single joined query, so the whole nested tree comes back in one
round trip instead of accumulating one query per relationship per row.

## Two real debugging trails worth remembering as patterns

**A cross-origin request failing with no useful detail.** The frontend and
backend run as different origins during local development, and browsers
block cross-origin requests by default unless the server explicitly opts
in. The browser's own error was a generic, unhelpful failure message with
no detail at all — the actual cause (the server rejecting the browser's
automatic pre-flight check) only showed up in the *server's* access log,
not the browser console. The underlying reason: the server process was
still running an old build from before cross-origin support was added,
because it had been started without automatic reload enabled. The general
lesson: when a cross-origin request fails silently, the server-side log is
often the faster diagnostic path than anything visible in the browser.

**A request that hangs instead of erroring.** After fixing the above, a
form submission got stuck indefinitely rather than showing any error — a
hang, not a crash, and initially invisible because the handler had no
error handling around it at all (adding that was the first fix, so future
failures would be visible rather than silent). The real cause, found in
the server log: a database connection timeout, because the local database
engine had stopped running in the background — the request passed
authentication successfully, then hung waiting for a database connection
that would never arrive. The general, transferable distinction: a request
that fails fast points at something rejecting it outright (usually
configuration); a request that hangs points at something downstream not
responding at all (usually infrastructure) — diagnosing which one you have
narrows the search dramatically before opening a single log file.

## What actually proved the whole chain works

Not a code review or a passing build — a real sign-in through the browser,
followed by direct inspection of the database: a new user record appeared
with the real identity format issued by the auth provider, distinct from
an earlier manually-seeded test user, and the resulting resource was
correctly scoped to that real user's ID, not the placeholder's. That's the
concrete proof the full chain works end to end: token issued, signature
verified, origin checked, identity extracted, user record created on
first sight, and the resulting write correctly scoped to the right owner.

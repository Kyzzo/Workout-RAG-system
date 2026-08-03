# Building the RAG Ingestion Pipeline

Covers corpus ingestion: reusing and adapting a prior RAG implementation,
the two-collection architecture (shared research corpus vs. private
per-user uploads), durable background jobs, and several real bugs caught
along the way — including one that would have silently broken retrieval
filtering on every future reset.

## Reusing prior work by actually reading it first

Rather than re-implementing PDF ingestion and retrieval from a description
of what it should do, the actual working code from an earlier, already-
built RAG project was read directly and adapted — reading the real prior
implementation first is what made "reuse" mean something concrete, instead
of re-deriving the same design from a one-line summary of what it does.
The PDF chunking and embedding logic transferred almost unchanged, since
it doesn't care about collections, categories, or users at all; the
storage layer and the ingestion job needed real adaptation for this
project's specific requirements.

## Two collections, one of them a hard privacy boundary

The vector store is split into two collections with different trust
models. One is a single shared, admin-ingested research corpus that every
user's retrieval draws from — nothing in it is private, so no per-user
filtering is needed. The other is where a user's own uploaded context
would live (injury history, their own prior programs, studies they want
considered) — every query against it has to filter by the requesting
user's ID.

That second filter is a genuine privacy boundary, not just a relevance
filter: one user's private uploads must never surface in another user's
retrieval results, the same way a well-designed multi-tenant system never
trusts client-side filtering alone for something that actually needs to
be enforced.

## Enforcing valid categories at the type level

Every ingested chunk is tagged with a research category, enforced through
a constrained type rather than a free string. Triggering ingestion with a
typo'd category fails immediately with a clear validation error, rather
than silently tagging content with a category that will never match a
real filter later — a substantially harder bug to notice, since it
wouldn't crash anything, it would just quietly make some content
unreachable by category-filtered retrieval from that point on.

## Durable background jobs instead of one long function

Ingestion work is split into named, independently-retryable steps rather
than one long function doing "load, chunk, embed, store" as a single unit.
A background-job library durably records each step's result as it
completes — if a later step fails (an embedding API call timing out, for
example), retrying only re-runs that specific step; earlier steps' results
aren't redone, and for a paid embedding API, aren't re-billed either. This
matters specifically for PDF ingestion because a single paper can produce
dozens of chunks, each needing its own API call — a transient failure
partway through a large batch would otherwise mean starting completely
over.

## Three real bugs, each worth remembering as its own category

**Trusting a previous version of a dependency's API.** Code carried over
from the earlier project used a background-job configuration field that
crashed immediately on import in this project — the field had been
renamed in the currently-installed version of that library. Checked the
actual installed package's own field definitions directly rather than
assuming previously-written code was still correct, and fixed the name
accordingly. The broader pattern, worth naming since it recurred multiple
times across this project in different libraries: even code written for
an earlier version of the *same* dependency isn't guaranteed to still
match a newer installed version — checking the real, current, installed
API beats trusting that prior code transfers unchanged.

**A hang traced to the operating system, not the application.** A local
database container was running, but connections to it simply hung with no
error at all, rather than failing or being rejected. Following the same
"a hang points at infrastructure, not application logic" principle that
had already paid off once elsewhere in this project, recreating the
container fresh produced a real, specific error instead — a socket-access
permission failure. That turned out to be a genuine operating-system-level
signal: the host OS had reserved a contiguous range of network ports
(from virtualization/container-networking infrastructure) that happened
to include the database's usual port and the first alternate port tried.
The fix was remapping to a port safely outside every reserved range — a
scoped, no-elevated-privileges-needed alternative to the more invasive
system-level fix.

**A required index that was never actually being created.** Filtering
retrieval by category failed outright with an explicit error demanding an
index on that field. The vector database only optimizes for similarity
search by default — filtering on a metadata field needs an explicit
secondary index, the same concept as a database index on a column, and
the platform refuses to even attempt an unindexed filter rather than
silently running a slow full scan. The real bug this exposed: the code
that creates a collection had never also created the index that
collection's own retrieval depends on — meaning a fresh setup on a new
machine would hit this same error the first time anyone tried filtered
retrieval, and a routine "wipe and recreate" reset script would silently
drop the index too, breaking filtering again on every future reset, since
recreating a collection only rebuilds the collection itself, not the
indexes it needs. Fixed at the actual source rather than patched around:
required indexes are now declared per collection and created
automatically in the same code path that creates the collection at all,
so the index can never be forgotten on setup or silently dropped by a
future reset — it's tied to the one place collections get created,
not a separate, memorizable manual step.

## What actually proved ingestion works, not just "succeeded"

A real research paper was ingested through the full pipeline and
confirmed to have landed in the vector store with the correct payload
fields. Re-ingesting the same source under a different identifier
correctly produced new, distinct entries rather than silently duplicating
or overwriting — confirming the deterministic ID scheme worked as
intended. Most importantly, a real natural-language query was run all the
way through embedding and retrieval, and it correctly surfaced the
paper's actual relevant content, not unrelated chunks — proving retrieval
*quality*, not just that ingestion technically completed without error.

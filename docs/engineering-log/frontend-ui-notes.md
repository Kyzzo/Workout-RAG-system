# Building the Frontend UI

Covers the first real UI work — a form and a result viewer — and a few
small, genuinely instructive bugs along the way.

## Server components and client components run in different places

The page-level component and the interactive form/viewer components are
split across separate files for a specific reason: they run in
fundamentally different places. The page-level component runs an
authorization check on the server, before any HTML is even sent to the
browser — this is what lets it check access *before* rendering anything,
rather than showing a page and then redirecting. The interactive pieces
are explicitly marked to run in the browser instead, which is required
because they use things that only exist there: component state that
persists across re-renders, a hook reading live client-side auth state,
and real user interaction handlers.

They can't be merged into one file: a server component's code never
reaches the browser at all — it runs once, produces HTML, and that's it.
Hooks and event handlers have no meaning in a context with no live,
running component tree to attach state or click handlers to. The moment a
page needs interactivity, that part has to be pulled into its own
browser-rendered file.

## Bridging a separate backend's auth boundary

The backend is a genuinely separate service (different origin) that the
frontend's auth provider has no direct connection to — the provider's
session state lives on the frontend side; the backend only ever sees
whatever gets explicitly attached to a request's authorization header. A
hook that returns the current session's token on demand is the bridge: it
hands back a real, currently-valid token that gets attached manually to
any outgoing request to the separate backend, using the same standard
bearer-token header format the backend's own auth verification expects.

## Async event handlers don't get automatic error handling

The first version of the form's submit handler had no error handling at
all. When something failed inside it, the failure became an unhandled
promise rejection — invisible to the user, no error message, no state
update, just nothing happening when the button was clicked. The reason:
rendering errors get caught automatically by a framework's error
boundaries, but a rejected promise inside an event handler doesn't get
the same treatment — it just vanishes into the browser's own unhandled-
rejection mechanism unless the handler explicitly catches it itself. The
fix: wrapping the whole handler in a try/catch/finally, so a real failure
becomes a visible error message instead of a silent nothing, and a
loading state gets reliably reset whether the request succeeded, failed,
or threw.

## A loading-state pattern that also aids debugging

A disabled submit button paired with a changing label serves two purposes
at once: the disabled state prevents a double submission if someone clicks
twice before the first request finishes; the label change gives visible
confirmation that a click actually registered. That visible state turned
out to be directly useful for debugging too — a button stuck permanently
on its "submitting" label was the exact visible signal that led to finding
an infrastructure problem downstream (a local database engine that had
stopped running), rather than that failure being silent the way an earlier
unhandled one had been.

## A dark-mode contrast bug from an inherited CSS variable

A result display box used an explicit light background color, but no
explicit text color — so it inherited the page's theme-aware foreground
color variable. In dark mode, that meant near-white text on a light gray
box: nearly invisible. The bug wasn't really in the component itself; it
was a global CSS variable meant for the page's own background silently
leaking into a component with a different, hardcoded background that
didn't participate in the same theme-awareness. The general, reusable
lesson: any time a component hardcodes one half of a background/text
color pair while the other half stays theme-aware through an inherited
variable, that mismatch is exactly how invisible-text bugs happen — the
fix is to make both halves of the pair explicit and theme-aware together,
not just one.

## Aligning sibling widths through a shared constraint

An input-and-button row and a result box below it initially had
independent width rules, so they didn't visually line up — the row sized
itself to its content, the box capped itself at a fixed maximum width
independently. Constraining width once, at a shared parent wrapper, and
then having every child stretch to fill that parent's full width, is what
keeps sibling elements aligned — versus each child guessing its own width
independently and hoping the numbers happen to match.

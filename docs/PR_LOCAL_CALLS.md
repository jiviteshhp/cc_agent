# Named browser calls, numbered PDFs, and Android hotspot access

## Outcome

Users enter a name and age, run a fresh browser conversation, and get a numbered
PDF such as `001Name.pdf`. A local call list persists across reloads. An optional
HTTPS launcher makes the same interface available to Android over the phone's
hotspot while the laptop runs the app. The setup guide covers a fresh clone,
API keys, local certificates, phone downloads, and Android Settings installation.

## Active phase

Local voice demo and friend reproduction. Deployment is deferred. The user
explicitly requested pushing `feat/android-hotspot-pdf-demo` without merging.
This branch includes the voice foundation from `share/local-optha-voice-demo`.

## Evidence

- [x] 101 offline Python tests pass; Node audio checks, JS syntax and diff whitespace pass.
- [x] Failure cases cover disconnect, extraction/save failure, concurrent numbering,
  certificate IP validation, host restrictions, and HTTPS/WSS origin checks.
- [x] Runtime secrets, certificates, patient artifacts and unrelated deployment files excluded.
- [x] Documentation and environment example updated.

Earlier real Chrome checks with synthetic providers passed identity submission,
numbered-download UI, audio cleanup, restart and mobile layout. The user now
confirms the demo works on their Android phone after installing the local CA.
This is not a measured live speech quality benchmark. One existing Starlette/httpx
deprecation warning remains. Linux is tested; Windows/macOS guide steps are unverified.

## Clinical or data impact

Clinical prompt and extraction fields are unchanged. Entered name/age go directly
into the existing PDF layout. Named call metadata is newly persisted in ignored
`state/browser_calls.sqlite3`; PDFs go under ignored `pdfs/local_calls/`. The
current PDF font expects English-spelled names. Use synthetic data for review.

## Reviewer notes

Follow `docs/ANDROID_HOTSPOT.md` from a fresh clone. Run two synthetic calls with
different identities and verify separate PDFs survive a page reload. Verify the
phone microphone and interruption on your own device. The laptop must remain
awake with the hotspot connected; speech/model APIs still require internet.
Failed attempts consume numbers; abrupt process death can leave an in-progress
row. Review only; do not merge until explicitly requested.

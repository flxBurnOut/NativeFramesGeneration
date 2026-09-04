# Pixel Sprite Generation Harness (V0.1)

[中文说明](README.zh-CN.md)

This local harness turns transparent character reference art and an action spec
into auditable PNG animation candidates, deterministic QA previews, and a staged
Godot-compatible Sprite Sheet. It follows the repository plan while keeping the
core independent from any one operator interface.

The same `SpritePipelineService` is used by:

- PixelLab Animate with Text V3 or an offline diagnostic provider;
- a JSON-only command line designed for direct Codex orchestration;
- a loopback REST API for another tool or script;
- a six-page, project-guided Gradio operator page.

It never writes into formal game asset directories or mixes normal user data
with source code. Runtime jobs and user character packages default to
`%LOCALAPPDATA%\SpritePipeline`; approved exports default to
`Documents\SpritePipeline\Exports`. Passing `--root` explicitly enables
portable/test mode.

## Implemented scope

- Versioned character/action presets with strict 64×64 or 128×128 cells.
- Durable JSON jobs, reference checksums, prompt snapshots, seeds, provider job
  IDs, redacted request/response records, usage, review state, and export hashes.
- PixelLab V3 submission and bounded background polling using the current
  official REST contract.
- Serial candidate generation; no credit-bearing POST retry after an ambiguous
  transport result.
- Live quota checks and an OS-backed cross-process lock around each chargeable
  submission, shared by the UI, REST API, and CLI.
- Documented dynamic unit estimation:
  `ceil(width * height * provider_frame_count / 65536)`. A 128x128,
  4/8/16-frame candidate costs approximately 1/2/4 subscription units.
- Idempotent task creation, append-only task revisions, background restart
  recovery, atomic result publication, and committed frame checksums.
- Successful responses with a different image count preserve every valid frame,
  surface a review warning, and pad the final project-width grid with transparent
  trailing cells instead of discarding paid output.
- Offline `fixture` provider for end-to-end diagnostics without a token. Its
  output is always marked `diagnostic_only` and is not production animation.
- Import from ordered PNG directories, animated GIFs, regular Sprite Sheets,
  and manifest-mapped sparse project sheets.
- Hard QA gates for count, dimensions, corruption, blank content, source alpha,
  configurable consecutive duplicate runs, and high-confidence abrupt
  frame-to-frame position jumps.
- Character-level warning thresholds for safe margins, area drift, centroid
  jumps, palette deviation, loop closure, and grounded baseline drift.
- Original/enlarged GIFs, enlarged indexed grid, adjacent-frame onion skins,
  project reference lines, and a preview sheet.
- Explicit per-frame review, a full repair timeline with pending, approved,
  repair-requested, modified, and blocking states, previous/next-problem
  navigation, a lossless in-browser pixel editor, unlimited local manual
  versions, two separately bounded external/future-AI replacements per bad
  frame, and deterministic staged export.
- Exported PNG, preview GIF, recipe JSON, and QA JSON.
- A project-guided UI with Guide & Example, Generate Animation, a separate
  Saved Assets library, Playback Review, Frame Repair, Export, and API/project
  settings. Character source upload and identity/action prompts are integrated
  into generation.
- A bundled Dreamweaver / Cyber Warrior profile: 128×128 RGBA cells, four
  columns, anchor (64,106), and a uniform sixteen-frame 4x4 / 512x512 output
  sheet for every new action while retaining project timing and filenames.
- Eleven bundled action templates. The project UI exposes idle, walk, jump,
  ground attack, air attack, hurt, backward evade, and defeated; three generic
  templates remain available to API/CLI users.
- Every bundled action now requests and exports sixteen frames. The generic
  import/recovery path still preserves valid non-sixteen and sparse legacy
  sheets instead of discarding existing or already-paid artwork.

PixelLab Edit Animation V2 and GPT-Image-2 automatic repair are intentionally
not in V0.1. The built-in editor already provides exact RGBA pencil, eraser,
eyedropper, exact four-connected fill, rectangular selection with integer-pixel
nudge, previous/next onion skins, position deltas, integer zoom, a non-exported
pixel grid, pan, undo/redo, bounded crash-recovery drafts, and verified manual
versions. Manual-save and QA status are reported separately, so a durable
version cannot be misreported as lost when a later preview check fails. A
repaired PNG can still be inserted with the separately bounded `replace-frame`
fallback. `replace-frame` also requires the source frame's captured SHA-256, so
an external editor cannot silently overwrite a newer version.

Drafts retain both the base and edited RGBA buffers. If another window changes
the durable frame, recovery performs a three-way pixel merge and only applies
non-conflicting changes; editing stays locked until the recovery choice is
resolved. Every page instance has an independent draft slot, preventing cloned
or late-closing tabs from overwriting each other. External replacement uploads
are likewise bound to the job, candidate, frame, and base SHA-256 captured when
the file was selected, and are cleared whenever that repair context changes.

Successful QA records its algorithm version. A candidate approved under an
older QA version may be rechecked before export and must then be approved again;
an exported candidate remains immutable. The export recipe and QA report both
record the QA algorithm version.

After a manual or external frame repair, the repair page persists and displays
an issue delta—resolved, new, and persisting—against the last successful QA.
If rechecking fails, that baseline remains available for a later retry.

For provider-generated candidates, the immutable source manifest, commit marker,
and raw PNGs are service-level prerequisites for QA, approval, and export. An
active repaired frame may differ from its raw source, but cannot hide source
corruption. Repeated recovery scans of the same persistent error are no-ops and
do not grow the append-only job journal indefinitely.

Codex may commit a same-size transparent PNG with `pixel-edit-frame`. Its
`--base-sha256` is mandatory and must be the hash captured when the source
frame was read, so a stale local edit cannot overwrite a newer UI/API/CLI
version.

## Install

Python 3.11 or newer is required.

```powershell
cd Tools\SpritePipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `python` is not on `PATH` on a Windows Codex host, bootstrap from the bundled runtime:

```powershell
$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $codexPython -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Save the PixelLab token from the UI's **API & Project** page; it takes effect
without restarting. Windows stores it with current-user DPAPI protection. The
token is only placed in the Bearer header, and persisted provider records redact
secrets and base64 image bodies. Automated deployments may use the process
environment variable `PIXELLAB_API_KEY`, but a real token should no longer be
stored in the repository `.env`.

## Add a character

Copy `presets/characters/_template/character.example.json` to
`presets/characters/<character_id>/character.json`, then add at least
`idle_reference.png`. The reference must match the configured 64×64 or 128×128
size, contain an alpha channel, and contain visible pixels.

Keep `identity_description` about identity only. Put anticipation, contact,
hold, recovery, and looping behavior in an action JSON under `presets/actions/`.
QA thresholds belong in the character preset rather than processing code.

The template leaves optional assets as `null`; set a filename only when that
asset is present. `list-presets` verifies referenced assets and marks broken
packages invalid.

## Offline smoke test

The bundled `diagnostic_dummy` and `fixture` exercise the complete workflow
without a token or network call. Their outputs are never production art:

```powershell
$created = .\harness.ps1 create --request examples\create_job.json | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 approve --job $jobId --candidate 1 --reviewer codex --acknowledge-warnings
.\harness.ps1 export --job $jobId --candidate 1
```

## Codex / JSON CLI

Every successful command prints one UTF-8 JSON object to stdout and exits `0`.
Expected validation/workflow errors also print one JSON object and exit `2`.
This makes commands safe for Codex to call and inspect without screen control.

From `Tools/SpritePipeline`:

```powershell
.\harness.ps1 list-presets
$created = .\harness.ps1 create --character your_character --action forward_thrust --provider pixellab --candidates 1 --request-key <stable-unique-value> | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 status --job $jobId
.\harness.ps1 safety --job $jobId --candidate 1
```

On a Windows Codex host where `python` is not on `PATH`, use the included
launcher; it checks `.venv`, `PATH`, then the bundled Codex runtime:

```powershell
.\harness.ps1 list-presets
```

If PowerShell execution policy blocks `.ps1` files, use the equivalent CMD
launcher without changing machine policy:

```powershell
.\harness.cmd list-presets
.\harness.cmd serve-ui
```

Every later `harness.ps1` example can be replaced verbatim with `harness.cmd`.

Each candidate is a separate generation submission, so the UI and examples
default to one. One submission can consume more than one subscription unit;
use `estimate --character <id> --action <id> --candidates <n>` first.
Generation is sequential when more are requested. `generate`
waits by default. Use `--no-wait` to advance one submission/poll step, then call
it again after inspecting the durable status. `recover-all` scans every durable
task using only existing provider IDs. A `submission_unknown` candidate must
never be resubmitted; attach a discovered original ID with
`attach-provider-job`. To salvage an older candidate
whose provider job completed but the former strict count check rejected, run
`harness.ps1 recover --job <id> --candidate <n>`; recovery only polls the
existing provider job and never submits a new generation.

Review warnings before approval. The explicit acknowledgement is deliberate:

```powershell
.\harness.ps1 approve --job $jobId --candidate 1 --reviewer codex --acknowledge-warnings
.\harness.ps1 export --job $jobId --candidate 1
```

For existing frames or another generation API, create an `import` job and feed
its output into the same checks:

```powershell
.\harness.ps1 create --character your_character --action forward_thrust --provider import --candidates 1
.\harness.ps1 ingest --job <job_id> --candidate 1 --source D:\candidate_frames --kind png_dir
```

Sprite Sheet import requires `--kind sheet --columns N`. Provider, GIF, and
directory inputs preserve their actual usable frame counts. A provider count
difference is a review warning; unreadable, inconsistent-size, or otherwise
invalid frames remain blocking failures.

See [CODEX_USAGE.md](CODEX_USAGE.md) for the stable orchestration contract and
repair flow.

## REST API

Start the loopback-only server:

```powershell
.\harness.ps1 serve-api
```

Interactive OpenAPI docs are at `http://127.0.0.1:8765/docs`. Main routes:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Local readiness and provider configuration |
| `GET` | `/v1/system/storage` | Separated data paths and migration status |
| `GET` | `/v1/account/balance` | Refresh the non-chargeable account balance |
| `GET` | `/v1/account/estimate` | Estimate dynamic generation units locally |
| `GET` | `/v1/jobs` | Read lightweight saved-task summaries without loading frames or previews |
| `POST` | `/v1/jobs` | Idempotent create from `GenerationRequest` JSON |
| `POST` | `/v1/jobs/{id}/generate` | Submit/poll one or all candidates |
| `GET` | `/v1/jobs/{id}` | Read the durable job record |
| `GET` | `/v1/jobs/{id}/candidates/{n}/safety` | Compact submit/result-integrity status |
| `POST` | `/v1/recovery/run` | Safely resume all durable tasks |
| `POST` | `/v1/jobs/{id}/candidates/{n}/recover` | Poll an existing provider job without submitting a generation |
| `POST` | `/v1/jobs/{id}/candidates/{n}/attach-provider-job` | Bind a known ID after an ambiguous submission |
| `POST` | `/v1/jobs/{id}/candidates/{n}/frames` | Import 1–64 base64 PNG frames |
| `POST` | `/v1/jobs/{id}/candidates/{n}/reviews/frame` | Save one frame review |
| `GET` | `/v1/jobs/{id}/candidates/{n}/frames/{frame}/pixel-edit` | Read exact RGBA pixels and the base version hash |
| `POST` | `/v1/jobs/{id}/candidates/{n}/frames/{frame}/pixel-edit` | Commit a verified manual RGBA version and re-run QA |
| `POST` | `/v1/jobs/{id}/candidates/{n}/approve` | Explicitly approve a candidate |
| `POST` | `/v1/jobs/{id}/candidates/{n}/export` | Export after the approval gate |

The API intentionally defaults to loopback and has no authentication. Do not
bind it to a public interface without adding access control and upload quotas.
Send an `Idempotency-Key` header when creating a task; retry the same request
with the same value after a client timeout to receive the original task.

## Operator UI

```powershell
.\harness.ps1 serve-ui
```

Open `http://127.0.0.1:7860`. The pages are Guide & Example, Generate Animation,
Saved Assets, Playback Review, Frame Repair, Export, and API & Project.
The Generate page returns after the durable submit step. Historical results and
the four-stage task safety center live in Saved Assets instead of below the
generation form. Closing or refreshing the browser does not stop the local
recovery worker; reopening the task shows its saved state.

Startup, the five-second catalog refresh, and changing the task selection read
only each task's small `summary.json`. Full job history, candidate frames, and
previews are loaded only after **Open selected task** is pressed. One task owns
one directory; all of that task's candidates are kept below it as
`raw/candidate_01`, `candidate_02`, and so on. A missing summary on a legacy task
is backfilled once from its canonical job record.

Generate Animation accepts the character source PNG, reusable identity prompt,
and action prompt on one page. A 128×128 single frame is used directly; a
four-column project Sheet automatically contributes its first visible cell.
Existing completed Sheets can be uploaded only from Playback Review, where a
numbered grid is shown before they enter inspection. Frame Repair embeds the
exact-pixel editor and a full five-state frame timeline. It can jump to the
previous or next problem frame and preserves the current job, candidate, and
frame after saves, rechecks, and external replacements. For looping actions,
the last frame is the first frame's “loop previous” neighbor and the first frame
is the last frame's “loop next” neighbor. External PNG upload remains a
collapsed, provenance-bound fallback.
The diagnostic dummy appears only under Example.

## Tests

The unified pytest entry runs the Python suite and, when Node.js is installed,
the pure pixel-editor core suite. Tests do not make paid or network calls:

```powershell
python -m pytest -q
```

The real-browser smoke test—load, draw exact pixels, undo/redo, save, reload,
and byte-compare the result—has not yet been run. Python/Node regression tests
must not be reported as a passed browser smoke test.

The offline fixture proves storage, QA, review, and export plumbing. A real
model feasibility run with project characters is still required before treating
PixelLab as an approved production backend, as required by the original plan.
The idle fixture keeps the complete alpha silhouette at one canvas position and
changes only a few interior RGB pixels because idle has no intended root motion.
Other actions may move naturally. Generation prompts request a smooth
frame-to-frame root trajectory, while QA blocks high-confidence sudden jumps
without cropping, resizing, recentering, or changing the fixed cell dimensions.
New Cyber Warrior generations use one uniform 512×512, 4x4, sixteen-frame
contract for every action. Existing lower-frame assets remain valid import and
review inputs. Jump, ground attack, air attack, and hurt need their Godot frame
lists updated before replacement; backward evade still requires a new animation
and state mapping because it is not present in the supplied project manifest.

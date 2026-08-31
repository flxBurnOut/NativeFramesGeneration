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

It never writes into formal game asset directories. Runtime jobs live under
`work/`, and approved exports live under `exports/`; both are ignored by Git.

## Implemented scope

- Versioned character/action presets with strict 64×64 or 128×128 cells.
- Durable JSON jobs, reference checksums, prompt snapshots, seeds, provider job
  IDs, redacted request/response records, usage, review state, and export hashes.
- PixelLab V3 submission and bounded background polling using the current
  official REST contract.
- Serial candidate generation; no credit-bearing POST retry after an ambiguous
  transport result.
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
- Explicit per-frame review, whole-candidate approval, two versioned replacement
  attempts per bad frame, and deterministic staged export.
- Exported PNG, preview GIF, recipe JSON, and QA JSON.
- A project-guided UI ordered as Guide & Example, Generate Animation, Playback
  Review, Frame Repair, and Export, with API/project settings last. Character
  source upload and identity/action prompts are integrated into generation.
- A bundled Dreamweaver / Cyber Warrior profile: 128×128 RGBA cells, four
  columns, anchor (64,106), and action-specific sheet height, playback cells,
  timing, and filenames from the project asset contract.
- Eleven bundled action templates. The project UI exposes idle, walk, jump,
  ground attack, air attack, hurt, backward evade, and defeated; three generic
  templates remain available to API/CLI users.
- PixelLab keeps its even 4–16 source-frame contract. The five-frame ground and
  air attacks generate six auditable source frames, then deterministically retain
  five project frames and export them into the existing sparse grid layouts.

PixelLab Edit Animation V2 and GPT-Image-2 automatic repair are intentionally
not in V0.1. A repaired PNG can already be inserted with `replace-frame`; this
keeps the review and export contract stable before adding another paid workflow.

## Install

Python 3.11 or newer is required.

```powershell
cd Tools\SpritePipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If `python` is not on `PATH` on a Windows Codex host, bootstrap from the bundled runtime:

```powershell
$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $codexPython -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Save the PixelLab token from the UI's **API & Project** page (it takes effect
without restarting), or put it in the local `.env` file:

```dotenv
PIXELLAB_API_KEY=your_token_here
```

The token is only placed in the Bearer header. Persisted provider records redact
secrets and base64 image bodies.

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
$created = .\harness.ps1 create --character your_character --action forward_thrust --provider pixellab --candidates 3 | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
.\harness.ps1 status --job $jobId
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

Generation is sequential even with three candidates. `generate` waits by
default. Use `--no-wait` to advance one submission/poll step, then call it again
after inspecting the durable status.

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

Sprite Sheet import requires `--kind sheet --columns N`. GIF and directory
imports preserve their actual frame counts so QA—not silent truncation—reports
a mismatch.

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
| `POST` | `/v1/jobs` | Create from `GenerationRequest` JSON |
| `POST` | `/v1/jobs/{id}/generate` | Submit/poll one or all candidates |
| `GET` | `/v1/jobs/{id}` | Read the durable job record |
| `POST` | `/v1/jobs/{id}/candidates/{n}/frames` | Import base64 PNG frames |
| `POST` | `/v1/jobs/{id}/candidates/{n}/reviews/frame` | Save one frame review |
| `POST` | `/v1/jobs/{id}/candidates/{n}/approve` | Explicitly approve a candidate |
| `POST` | `/v1/jobs/{id}/candidates/{n}/export` | Export after the approval gate |

The API intentionally defaults to loopback and has no authentication. Do not
bind it to a public interface without adding access control and upload quotas.

## Operator UI

```powershell
.\harness.ps1 serve-ui
```

Open `http://127.0.0.1:7860`. The pages are Guide & Example, Generate Animation,
Playback Review, Frame Repair, Export, and API & Project.
Long PixelLab calls may occupy the local UI request; the JSON CLI or REST
`wait=false` mode is better for external orchestration.

Generate Animation accepts the character source PNG, reusable identity prompt,
and action prompt on one page. A 128×128 single frame is used directly; a
four-column project Sheet automatically contributes its first visible cell.
Existing completed Sheets can be uploaded only from Playback Review, where a
numbered grid is shown before they enter inspection. Repair uploads stay on
their own page, and the diagnostic dummy appears only under Example.

## Tests

Core tests use `unittest` and do not make paid or network calls:

```powershell
python -m unittest discover -s tests -v
```

The offline fixture proves storage, QA, review, and export plumbing. A real
model feasibility run with project characters is still required before treating
PixelLab as an approved production backend, as required by the original plan.
The idle fixture keeps the complete alpha silhouette at one canvas position and
changes only a few interior RGB pixels because idle has no intended root motion.
Other actions may move naturally. Generation prompts request a smooth
frame-to-frame root trajectory, while QA blocks high-confidence sudden jumps
without cropping, resizing, recentering, or changing the fixed cell dimensions.
Cyber Warrior outputs match the existing assets: 512×512 for idle, walk, and
defeated; 512×384 for jump, hurt, and air attack; and 512×256 for ground attack
and the new backward evade. Backward evade is export-ready but still requires a
new Godot animation/state mapping because it is not present in the supplied
project manifest.

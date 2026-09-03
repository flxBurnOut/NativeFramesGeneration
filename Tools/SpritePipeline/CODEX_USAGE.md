# Codex driver contract

Codex should operate the harness through `cli.py`, not by clicking Gradio. The
CLI is non-interactive, emits one UTF-8 JSON value, and persists every state
transition before moving to the next paid or destructive boundary.

On Windows, use `harness.cmd` when PowerShell execution policy blocks
`harness.ps1`; both launch the same JSON CLI.

## Safe orchestration sequence

1. Call `list-presets`; stop if the requested character/action is absent or
   marked invalid.
2. Call `create` once and retain `data.job.job_id` from the JSON response.
3. For PixelLab, call `generate --job <id>`. For async control, add `--no-wait`
   and inspect `data.job.candidates[*].status` before calling again.
   Start with one candidate because each candidate is a separate paid generation.
4. Inspect each candidate's `hard_failures`, `warnings`, frame records, and the
   files in `work/<id>/previews/`.
5. Never approve a hard failure. When warnings are acceptable, record the
   decision with `approve --acknowledge-warnings --reviewer codex`.
6. If a frame needs repair, mark it first with `review-frame --status
   repair_requested --issue <category>`, produce or obtain a fixed 64/128 PNG,
   then call `replace-frame`. At most two replacement versions are accepted.
7. Call `export` only after the candidate status is `approved`. Do not add
   `--overwrite` unless the user explicitly wants to replace an existing staged
   export.
8. Report the four paths and sheet checksum from `data.job.export`.

For the bundled Cyber Warrior, use action IDs `idle`, `walk`, `jump`, `attack`,
`attack_in_air`, `hurt`, `backward_evade`, or `death`. Do not reconstruct sheet
order yourself: the service automatically applies the action's fixed dimensions,
playback cells, transparent unused cells, runtime FPS, and critical-frame metadata.
Ground and air attack have five project frames but six provider source frames;
the raw provider directory preserves all six for audit. `backward_evade` is a new
asset contract and must not be reported as already wired into the Godot state machine.

## Statuses Codex must respect

Candidate states are `created`, `submitting`, `provider_pending`, `received`,
`check_failed`, `review_ready`, `approved`, `rejected`, and `failed`.

- `submitting` with no provider job ID means a submission may have succeeded but
  its result is unknown. Do not automatically resubmit; doing so can double
  charge the account.
- `provider_pending` is resumable using another `generate` call.
- A failed candidate whose `provider_status` is `completed` and whose error is
  the former frame-count contract can be salvaged with `recover --job <id>
  --candidate <n>`. `recover` polls the existing provider job and never submits.
- `check_failed` is never exportable.
- `review_ready` requires explicit review/approval.
- `fixture` results are diagnostic only even if QA passes.

## Stable examples

Create from flags:

```powershell
.\harness.ps1 create --character your_character --action idle --provider pixellab --candidates 1 --seed 12345
```

Run the bundled, offline diagnostic from a versioned request file:

```powershell
$created = .\harness.ps1 create --request examples\create_job.json | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
```

Mark a bad frame and replace it:

```powershell
.\harness.ps1 review-frame --job <id> --candidate 1 --frame 5 --status repair_requested --issue weapon_error --note "blade bends and changes length" --reviewer codex
.\harness.ps1 replace-frame --job <id> --candidate 1 --frame 5 --source D:\repairs\frame_005.png
```

Reject a candidate without modifying its immutable raw frames:

```powershell
.\harness.ps1 reject --job <id> --candidate 2 --reviewer codex --note "identity drift"
```

The CLI JSON schema starts at `schema_version: 1`. Treat unknown fields as
forward-compatible, but do not ignore `ok: false`, nonzero exit codes, hard
failures, or an unapproved candidate state.

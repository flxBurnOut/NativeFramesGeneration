# Codex driver contract

Codex should operate the harness through `cli.py`, not by clicking Gradio. The
CLI is non-interactive, emits one UTF-8 JSON value, and persists every state
transition before moving to the next paid or destructive boundary.

On Windows, use `harness.cmd` when PowerShell execution policy blocks
`harness.ps1`; both launch the same JSON CLI.

## Safe orchestration sequence

1. Call `list-presets`; stop if the requested character/action is absent or
   marked invalid.
2. Call `create` with a stable `--request-key` and retain
   `data.job.job_id`. Repeating the same key and request returns that job.
3. For PixelLab, call `generate --job <id>`. For async control, add `--no-wait`
   and inspect `data.job.candidates[*].status` before calling again.
   Start with one candidate because each candidate is a separate paid POST.
   Call `estimate` first: subscription units follow
   `ceil(width * height * frame_count / 65536)`, so one 128x128, 16-frame
   candidate costs 4 units rather than 1.
4. Call `safety --job <id> --candidate <n>`, then inspect each candidate's
   `hard_failures`, `warnings`, and frame records. Use `storage-status` to
   discover the per-user jobs directory; never assume a repository `work/`.
5. Never approve a hard failure. When warnings are acceptable, record the
   decision with `approve --acknowledge-warnings --reviewer codex`.
6. If a frame needs repair, mark it first with `review-frame --status
   repair_requested --issue <category>`. For a lossless local/manual edit, call
   `pixel-edit-frame`; these versions do not consume provider credits and are
   not limited to two. Reserve `replace-frame` for the external/future-AI
   replacement path, which accepts at most two versions.
7. Call `export` only after the candidate status is `approved`. Do not add
   `--overwrite` unless the user explicitly wants to replace an existing staged
   export.
8. Report the four paths and sheet checksum from `data.job.export`.

For the bundled Cyber Warrior, use action IDs `idle`, `walk`, `jump`, `attack`,
`attack_in_air`, `hurt`, `backward_evade`, or `death`. Do not reconstruct sheet
order yourself: every new bundled action requests sixteen frames and exports a
four-column, four-row sheet while preserving runtime FPS and critical-frame
metadata. Valid non-sixteen provider results and legacy Sheet imports must still
be preserved for review instead of being resubmitted or discarded.
`backward_evade` is a new asset contract and must not be reported as already
wired into the Godot state machine. Jump, attack, air attack, and hurt also need
their existing Godot frame lists updated before a new sixteen-frame export can
replace an older lower-frame asset.

## Statuses Codex must respect

Candidate states are `created`, `submitting`, `submission_unknown`,
`provider_pending`, `saving`, `received`, `check_failed`, `review_ready`,
`approved`, `rejected`, and `failed`.

- `submitting` is a persisted in-flight POST. If it becomes stale without a
  provider job ID, recovery changes it to `submission_unknown`.
- `submission_unknown` must never be resubmitted. If the original provider job
  ID is found, use `attach-provider-job`; that command never submits.
- `provider_pending` is resumable using another `generate` call.
- `saving` means the provider completed but local publication is unfinished.
  Run `recover-all`; it publishes a committed staging result or polls the same
  provider job, never a new one.
- A failed candidate whose `provider_status` is `completed` and whose error is
  the former frame-count contract can be salvaged with `recover --job <id>
  --candidate <n>`. `recover` polls the existing provider job and never submits.
- `check_failed` is never exportable.
- `review_ready` requires explicit review/approval.
- `fixture` results are diagnostic only even if QA passes.

## Stable examples

Create from flags with an idempotency key:

```powershell
.\harness.ps1 create --character your_character --action idle --provider pixellab --candidates 1 --seed 12345 --request-key <stable-unique-value>
```

Run the bundled, offline diagnostic from a versioned request file:

```powershell
$created = .\harness.ps1 create --request examples\create_job.json | ConvertFrom-Json
$jobId = $created.data.job.job_id
.\harness.ps1 generate --job $jobId
```

Mark a bad frame and commit a local pixel-edit PNG:

```powershell
.\harness.ps1 review-frame --job <id> --candidate 1 --frame 5 --status repair_requested --issue weapon_error --note "blade bends and changes length" --reviewer codex
.\harness.ps1 pixel-edit-frame --job <id> --candidate 1 --frame 5 --source D:\repairs\frame_005.png --base-sha256 <current-frame-sha256> --reviewer codex
```

`--base-sha256` prevents a stale edit from overwriting a frame changed in
another UI/API session. It may be omitted for a one-shot local operation, in
which case the service reads the current hash immediately before committing.
The command verifies an exact RGBA PNG round trip, preserves the immutable raw
frame, records changed-pixel metadata, and re-runs QA.

Reject a candidate without modifying its immutable raw frames:

```powershell
.\harness.ps1 reject --job <id> --candidate 2 --reviewer codex --note "identity drift"
```

The CLI JSON schema starts at `schema_version: 1`. Treat unknown fields as
forward-compatible, but do not ignore `ok: false`, nonzero exit codes, hard
failures, or an unapproved candidate state.

Normal runs separate code and user data. `storage-status` reports the actual
data, job, export, and protected-credential paths. `balance` performs a free
balance query, while `estimate` is entirely local. `recover-all`, `recover`, `safety`, and
`attach-provider-job` never create a chargeable submission. Only pass
`--root` for an explicitly requested portable/test workspace.

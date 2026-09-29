# Edge cases: where each is handled and which test pins it

The edge cases in [`DESIGN.md`](DESIGN.md) §8–§10, checked one by one in Phase 12d. Tests are in
`backend/tests/`; run them with `make test`.

## Property input

| Edge case | Behaviour | Test |
|---|---|---|
| Pin outside the service area, or `(0,0)` | Refused (422) with the reason | `test_scouting::test_bad_input_is_rejected_with_a_reason` |
| Pin in water / sea | Refused (422) | `test_scouting::test_pin_in_water_is_rejected` |
| Poor or missing GPS accuracy; pin far from the executive | Warnings, never a block | `test_scouting::test_warnings_never_block_the_save` |
| Duplicate (≤ 25 m + similar name), incl. the same shop from two executives | Flagged; explicit "same" / "different"; never silently merged or blocked | `test_scouting::test_duplicate_is_flagged_and_resolved_explicitly`, `…test_far_or_dissimilar_is_not_a_duplicate` |
| Rent negative / wrong unit / far outside the band | Negative refused; per-month vs per-sq-ft normalised; outliers warned | `test_scouting::test_bad_input_is_rejected_with_a_reason`, `…test_warnings_never_block_the_save` |
| Missing rent or area | Saved; recommendation **Needs Info**, never a guess | `test_pipeline::test_missing_rent_is_needs_info_never_a_guess` |
| Photo upload fails | Property already saved; photos separate; flagged incomplete | `test_scouting::test_photos_are_optional_and_uploaded_separately` |
| Property edited after evaluation | New evaluation version (trigger `edited`); old versions immutable | `test_pipeline::test_edit_creates_v2_and_versions_are_immutable` |
| Retried submit (flaky network) | Idempotent by client id | `test_scouting::test_save_first_and_retry_is_idempotent` |

## Pipeline

| Edge case | Behaviour | Test |
|---|---|---|
| Two managers move the same property | Second gets 409 (optimistic lock); UI re-reads, keeps the reason | `test_pipeline::test_concurrent_moves_conflict` |
| Reject → reopen | Allowed, reason required, audited | `test_pipeline::test_reject_then_reopen` |
| Executive tries to move a stage | 403 | `test_pipeline::test_only_the_manager_moves_stages_and_every_move_needs_a_reason` |
| Study on an already fresh-covered property | Reuse path ("reuse only" rolls up straight away), not an error | `test_rollup::test_reuse_only_rolls_up_straight_after_planning` |
| Property rejected with an open study | Study cancelled, captured data kept and reusable | `test_studies::test_rejecting_mid_study_cancels_it_and_keeps_the_data` |

## Analysis

| Edge case | Behaviour | Test |
|---|---|---|
| Selection too small / too large | Refused with the caps explained | `test_area_report::test_bad_selections_are_rejected_with_a_reason`, `…test_cell_edits_and_caps` |
| Area mostly sea / airport / empty | "Insufficient data", no score | `test_area_report::test_airport_is_insufficient_data_not_a_fake_score`, `test_scoring::test_mostly_unscoreable_selection_is_insufficient_data` |
| Too much weight missing | Facts only, no rating | `test_scoring::test_too_much_missing_weight_gives_facts_only` |
| Same area analysed twice | New immutable version, comparable | `test_area_report::test_report_end_to_end_and_versioning`, `…test_reports_are_immutable` |
| Ambiguous locality name | Candidates listed, never a guess | `test_reference::test_ambiguous_name_returns_several_candidates_not_a_guess` |
| Non-contiguous picked cells | Allowed, flagged | `test_area_report::test_non_contiguous_selection_is_allowed_but_flagged` |
| LLM timeout / invalid JSON / invented numbers | Retry with feedback → other provider → template; source recorded | `test_llm::*` (11 tests, incl. `test_forced_failure_everywhere_falls_back_to_template`) |
| Stores cache too old | Cannibalisation excluded with the cache age; weights renormalised; hard flag still uses the last known list | `test_pipeline::test_a_stale_stores_cache_excludes_cannibalisation_and_says_why` (added in 12d) |

## Survey

| Edge case | Behaviour | Test |
|---|---|---|
| Stale past data | Never reused, whatever the override | `test_studies::test_reuse_is_length_weighted_and_stale_is_never_reused` |
| Gated / inaccessible lane | "Could not survey" + reason: handled, not covered | `test_studies::test_could_not_survey_is_handled_but_not_covered` |
| Unit submitted twice | Idempotent no-op; late captures refused | `test_capture::test_latest_capture_counts_and_the_unit_submits_when_every_lane_is_handled` |
| Assigned executive unavailable | Reassign keeps captured data (audited); unassign refused once captured | Code: `services/units.py::assign`. Only one Survey Executive is seeded, so a real reassignment isn't exercised by a test |
| Old offline draft / wrong phone clock | > 7 days refused, future time refused | `test_capture::test_device_time_is_checked` |
| Capture far from the lane | Flagged (distance stored), not refused | `test_capture::test_far_gps_is_flagged_not_refused` |
| Captures from an older data snapshot | Count only if the segment is unchanged | `test_studies::test_captures_from_an_older_snapshot_count_only_if_the_segment_is_unchanged` |

## Failure handling

| Failure | Behaviour | Test |
|---|---|---|
| Worker dies mid-job | Heartbeat lost → re-queued → resumes at the failed step | `test_jobs::test_dead_worker_job_is_requeued_and_resumes` |
| A step fails | Named in the UI; retry resumes from it | `test_jobs::test_failed_step_is_named_and_retry_resumes_from_it` |
| Unknown job kind (old worker) | Job fails cleanly; the worker survives | `test_jobs::test_an_unknown_job_kind_fails_cleanly_instead_of_killing_the_worker` |
| Two workers | Never claim the same job | `test_jobs::test_two_workers_never_claim_the_same_job` |
| Config changed without a version bump | Refused at startup | `test_config::test_changed_content_under_same_version_is_refused` |

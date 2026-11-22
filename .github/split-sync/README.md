# Split reader publication gate

Before updating Next, audit every release row and the release manifest with `verify-retained-objects.py` against a full retained data commit and its `retain-<commit>` tag. Run the `gate` mode only after every chunk passes. Then use `guarded-next-push.py` with the verified manifest, gate receipts, corrected Original confirmation, candidate and expected remote head. Its default is read-only; `--publish` performs the guarded fast-forward push. Keep old retained objects and tags for rollback.

The gate verifies exact response URLs, CORS, byte lengths and SHA-256, and refuses incomplete or stale audit receipts. A tagged, browser-tested rollback commit must also be available before publishing. These tools do not automatically run on arbitrary Git pushes; do not bypass them. Retained commit and tag availability, host capacity and the Original cohort must be checked for every release.

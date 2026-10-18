# Personal validation route

The primary Gitea workflow retains the original Python3.13 lint and complete
unit tests, followed by the pinned official Home Assistant hassfest image.
Tests use fake HTTP responses, synthetic player state and mocked services;
no subscriber login, external playback, device control or HA restart is needed.
No integration runtime or published release version changes in this migration.

HACS compatibility is a separate manual gate using the pinned official image.
It requires `HACS_PUBLIC_READ_TOKEN` at repository scope, verifies Daniel's
GitHub identity and the existing public repository1372756742, and requires the
exact workflow SHA already present in recovery. It posts no PR comments and
ignores no checks. Do not claim that gate passed before its actual result.

After the private source gates pass, push the same commit to GitHub recovery
with Actions disabled and verify no checks, workflows or deployments were
created. Preserve public HACS distribution URLs and existing tags. The original
validation had no periodic schedule or automatic release publisher.

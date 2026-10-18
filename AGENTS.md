# KSLive personal project

This is Daniel's personal audio integration, unrelated to KG Solutions/Kidde.
Use private VM300 `hallyaus/ha-kslive` as origin, SSH2222 with the personal key.
Push completed commits to Gitea first and the identical validated commits to the
existing public GitHub recovery copy. GitHub Actions stay disabled.

Only the personal runner may validate this repository. Preserve Python3.13,
the complete lint and mocked unit gates, and official hassfest. The separate
manual HACS gate requires a repository-only personal read token and checks the
exact identical public recovery commit before running the pinned official image.
Never substitute a Gitea job token or ignore original HACS checks.

Do not log in to a real subscriber account, play a stream, change speakers/EQ,
install/reload the integration or restart HA as a test. Preserve idle sleep,
credential redaction, signed-stream privacy and existing release tags.
The existing public HACS/update URLs remain compatibility consumers until a
verified replacement exists. Private CI success is not an installed release.
Keep Made 4 Tradies, Proxmox.99 and Kidde outside this work.

# SwitchGamesBrowser Data

Public metadata distribution for SwitchGamesBrowser. The Browser's **source code, application builds, installation workers, and Android app remain in the private repository**.

## Public catalog generation

GitHub Actions in this repository regenerate and publish public data directly, using only the public generator scripts checked in here:

- **Update public IGDB catalog and covers** — 04:00 Singapore daily; produces `igdb-switch-games.json`, `covers-manifest.json` and `covers-*.pack`.
- **Update public Batman catalog** — 05:30 Singapore daily; produces `notultranx-catalog.json`. An incomplete site scan fails rather than replacing working data.

Both also support **Run workflow** from the Actions tab. No private-repository checkout or cross-repository personal access token is required. The public repo's `GITHUB_TOKEN` can commit its own generated files when Actions workflow permissions allow writes.

**Initial setup:** In this repository, configure the Actions secrets `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` (Settings → Secrets and variables → Actions). Those values must be set here separately; GitHub does not copy secrets between repositories. The Batman workflow does not need credentials.

Only public catalog and cover files are committed to the root. The `data/` build staging directory is ignored. Source changes to the private SwitchGamesBrowser repo do not trigger public app builds.

Other catalog shards are retained for compatibility with existing Browser versions, but there is no recurring public torrent-index generation workflow.

Do not commit credentials, private config, signed download URLs, game packages, or private application sources here.

# release-tools

Shared GitHub Actions for releasing chunkzero projects. Every project releases the same way:

1. Keep the **upcoming** release version in the project's version file, e.g. `0.1.0` or `0.1.0-beta.1`. Bump it after each
   release.
2. Compute the build's version once with `version` and pass it to every build step.
3. Build and verify every artifact, then publish Maven artifacts before the GitHub release that depends on them.
4. Publish the release with `publish`, then register CLI archives with `mise-registry`.

| Channel | Version | Published as |
|---|---|---|
| Stable | `0.1.0` | GitHub release marked latest |
| Prerelease | `0.1.0-alpha.1`, `0.1.0-beta.1`, `0.1.0-rc.1` | GitHub prerelease |
| Nightly | `0.1.0-nightly.20261004062300.ge282f11816cd` (UTC commit time, 12-character commit) | GitHub prerelease |

Versions are immutable: a commit always gets the same nightly version, a published release is never modified, and nothing
deletes old releases, so exact pins and lockfiles keep working.

```yaml
- id: version
  uses: chunkzero/release-tools/version@v1
  with:
    base: ${{ steps.base.outputs.version }}
    channel: nightly

- uses: chunkzero/release-tools/publish@v1
  with:
    version: ${{ steps.version.outputs.version }}
    directory: dist
    title: Chunk

- uses: chunkzero/release-tools/mise-registry@v1
  with:
    tool: chunk
    version: ${{ steps.version.outputs.version }}
    directory: dist
    token: ${{ steps.registry-token.outputs.token }}
```

`version` also reports `published: true` when that version is already public, so scheduled nightlies can skip unchanged
commits. CLI archives must be named `<tool>-<version>-<platform>.tar.gz`, with platforms `linux-x64`, `linux-arm64`,
`darwin-x64`, `darwin-arm64` and `windows-x64`, and contain one top-level directory holding the executable.

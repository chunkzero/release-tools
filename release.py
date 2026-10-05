#!/usr/bin/env python3
"""Compute release versions, publish immutable GitHub releases, and describe them for the mise registry."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

BASE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(?:alpha|beta|rc)\.\d+)?")
PLATFORMS = ("linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64", "windows-x64")


def run(*args):
    return subprocess.check_output(args, text=True)


def nightly_version(base, sha, committed):
    """`<major.minor.patch>-nightly.<UTC commit time>.g<sha12>`; the same commit always gets the same version."""
    match = BASE.fullmatch(base)
    if not match or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"invalid base version {base!r} or commit {sha!r}")
    timestamp = committed.astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{'.'.join(match.groups())}-nightly.{timestamp}.g{sha[:12]}"


def release_version(base, ref):
    if not BASE.fullmatch(base):
        raise ValueError(f"release versions must be X.Y.Z or X.Y.Z-(alpha|beta|rc).N, got {base!r}")
    if ref.startswith("refs/tags/") and ref != f"refs/tags/v{base}":
        raise ValueError(f"tag {ref} does not match the project version {base}")
    return base


def verify_checksums(assets):
    for path in assets:
        if path.suffix != ".sha256":
            expected = path.with_name(path.name + ".sha256").read_text().split()[0]
            if expected != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError(f"checksum mismatch: {path.name}")


def api(path):
    """GitHub API response, or None only when GitHub answers 404; any other failure raises."""
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "HTTP 404" in result.stderr:
        return None
    raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()}")


def find_release(repository, tag):
    """The release for `tag`, published or draft, or None."""
    published = api(f"repos/{repository}/releases/tags/{tag}")
    if published:
        return published
    # Drafts are only reachable through the release list.
    pages = json.loads(run("gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    return next((release for page in pages for release in page if release["tag_name"] == tag), None)


def tag_commit(repository, tag):
    """Commit the tag points at, following annotated tags, or None when the tag doesn't exist."""
    ref = api(f"repos/{repository}/git/ref/tags/{tag}")
    if ref is None:
        return None
    target = ref["object"]
    while target["type"] == "tag":
        target = api(f"repos/{repository}/git/tags/{target['sha']}")["object"]
    return target["sha"]


def verify_uploaded(repository, tag, assets):
    with tempfile.TemporaryDirectory() as temporary:
        run("gh", "release", "download", tag, "--repo", repository, "--dir", temporary)
        downloaded = Path(temporary)
        if sorted(path.name for path in downloaded.iterdir()) != [path.name for path in assets]:
            raise ValueError("release assets differ from the verified build")
        for path in assets:
            if path.read_bytes() != (downloaded / path.name).read_bytes():
                raise ValueError(f"uploaded asset differs: {path.name}")


def publish(repository, version, sha, directory, title):
    """Create or resume a draft, upload and re-download every asset, then publish. Published releases never change.

    Callers must not publish the same version concurrently, e.g. with a workflow `concurrency` group."""
    tag = f"v{version}"
    assets = sorted(path for path in directory.iterdir() if path.is_file())
    if not assets:
        raise ValueError("release has no assets")
    verify_checksums(assets)
    existing = find_release(repository, tag)
    # A draft has no tag until it's published, so its target is the only record of its commit.
    commit = tag_commit(repository, tag) or (existing["target_commitish"] if existing else sha)
    if commit != sha:
        raise ValueError(f"{tag} already belongs to {commit}, not {sha}")
    if existing and not existing["draft"]:
        verify_uploaded(repository, tag, assets)
        print(f"{tag} is already published with identical assets")
        return
    if existing:
        names = {path.name for path in assets}
        for asset in existing["assets"]:
            if asset["name"] not in names:
                run("gh", "release", "delete-asset", tag, asset["name"], "--repo", repository, "--yes")
    else:
        run("gh", "release", "create", tag, "--repo", repository, "--draft", "--target", sha,
            "--title", f"{title} {version}", "--notes", f"Source commit: {sha}\n")
    run("gh", "release", "upload", tag, "--repo", repository, "--clobber", *map(str, assets))
    verify_uploaded(repository, tag, assets)
    flags = ["--prerelease", "--latest=false"] if "-" in version else ["--prerelease=false", "--latest"]
    run("gh", "release", "edit", tag, "--repo", repository, "--draft=false", *flags)


def registry_entry(tool, version, repository, directory):
    """Registry version entry for `<tool>-<version>-<platform>.tar.gz` archives and their `.sha256` files."""
    tag = f"v{version}"
    assets = {}
    for platform in PLATFORMS:
        archive = directory / f"{tool}-{version}-{platform}.tar.gz"
        if archive.exists():
            verify_checksums([archive])
            assets[platform] = {
                "url": f"https://github.com/{repository}/releases/download/{tag}/{archive.name}",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
    if not assets:
        raise ValueError(f"no {tool}-{version}-<platform>.tar.gz archives in {directory}")
    return {"version": version, "tag": tag, "assets": assets}


def output(**values):
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as file:
            file.write(lines)
    print(lines, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version")
    version.add_argument("--base", required=True, help="the upcoming release, e.g. 0.1.0 or 0.1.0-beta.1")
    version.add_argument("--channel", choices=["nightly", "release"], required=True)
    version.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    version.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    version.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    publish_command = commands.add_parser("publish")
    publish_command.add_argument("--version", required=True)
    publish_command.add_argument("--directory", type=Path, required=True)
    publish_command.add_argument("--title", required=True)
    publish_command.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    publish_command.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    entry = commands.add_parser("registry-entry")
    entry.add_argument("--tool", required=True)
    entry.add_argument("--version", required=True)
    entry.add_argument("--directory", type=Path, required=True)
    entry.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args()

    if args.command == "version":
        if args.channel == "nightly":
            committed = datetime.datetime.fromtimestamp(int(run("git", "show", "-s", "--format=%ct", args.sha)),
                                                        datetime.timezone.utc)
            value = nightly_version(args.base, args.sha, committed)
        else:
            value = release_version(args.base, args.ref)
        published = find_release(args.repository, f"v{value}") if args.repository else None
        output(version=value, tag=f"v{value}", published=str(bool(published and not published["draft"])).lower())
    elif args.command == "publish":
        publish(args.repository, args.version, args.sha, args.directory, args.title)
    else:
        print(json.dumps(registry_entry(args.tool, args.version, args.repository, args.directory), indent=2))


if __name__ == "__main__":
    main()

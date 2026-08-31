"""Deterministic gate for what the image installs.

Pure-Python: reads `requirements.txt`, `requirements.lock.txt` and the `Dockerfile` as text. No
network and no resolve — proving a sha IS the tag beside it needs the credential and stays the
regeneration step's job (the lock's own header). What is asserted here is the property whose
violation is SILENT: every one of these can be wrong and the build still succeeds.
"""

from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pins(name: str) -> dict[str, str]:
    """Package -> its `git+` line, for the direct platform pins only."""
    return {
        line.split("@")[0].strip(): line
        for line in (_ROOT / name).read_text(encoding="utf-8").splitlines()
        if "git+" in line and not line.lstrip().startswith("#")
    }


def test_the_image_installs_the_lock_and_not_requirements() -> None:
    """The lock is only load-bearing if it is what the image installs. Installing requirements.txt
    beside it leaves every transitive floating again, with the lock in the tree to say otherwise."""
    docker = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    installs = [ln for ln in docker.splitlines() if "pip install" in ln]
    assert installs, "the Dockerfile installs nothing"
    for line in installs:
        assert "requirements.lock.txt" in line, f"the image installs off the lock: {line.strip()}"
        assert "-r requirements.txt" not in line, (
            f"the image also installs the floating pins: {line.strip()}"
        )


def test_every_requirements_pin_appears_in_the_lock() -> None:
    """`helm rollback` to revision N only pins an artifact if the image installed from the lock. A
    package added to requirements.txt but not carried into the lock is installed at whatever
    resolves that day — silently, because the build still succeeds."""

    def names(text: str) -> set[str]:
        out = set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name = line.split("@")[0].split("==")[0].split(">=")[0].strip()
            out.add(name.split("[")[0].lower())
        return out

    missing = names((_ROOT / "requirements.txt").read_text(encoding="utf-8")) - names(
        (_ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    )
    assert not missing, f"in requirements.txt but absent from the lock: {sorted(missing)}"


def test_the_lock_pins_agent_platform_by_commit_not_tag() -> None:
    """A tag can move and a sha cannot, which is the whole reason the lock exists separately from
    requirements.txt."""
    for line in (_ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        if "git+" in line and not line.lstrip().startswith("#"):
            ref = line.split("@")[-1].split("#")[0]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (
                f"the lock pins a ref that is not a commit sha: {ref}"
            )


def test_the_lock_and_requirements_name_the_same_version() -> None:
    """CI installs requirements.txt and the image installs the lock, so a pin moved in one and not
    the other ships a package no test ever ran, with a green build. The trailing tag comment is
    what makes the two comparable without the network."""
    lock = _pins("requirements.lock.txt")
    for pkg, line in _pins("requirements.txt").items():
        assert pkg in lock, f"{pkg} is pinned by git in requirements.txt but not in the lock"
        wanted = line.split("@")[-1].split("#")[0].strip()
        _, tagged, claimed = lock[pkg].rpartition("  # ")
        assert tagged, f"the lock pins {pkg} by sha with no comment naming the version it is"
        assert claimed.strip() == wanted, (
            f"{pkg}: requirements.txt installs {wanted}, the lock claims {claimed.strip()}"
        )

"""Sign a release descriptor binding the verified ZIP to its tag and source commit."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from package import PACKAGE_NAME
from validate import ROOT, require, validate


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sign(directory):
    manifest, _ = validate(report=False)
    version = manifest["version"]
    tag = f"v{version}"
    require(os.environ["GITHUB_REF"] == f"refs/tags/{tag}", "Tag must match manifest version")
    commit = git("rev-parse", "HEAD")
    require(commit == os.environ["GITHUB_SHA"] and not git("status", "--porcelain"),
            "Only a clean tagged source commit may be signed")
    archive = directory / f"{PACKAGE_NAME}-{version}-windows-x64.zip"
    data = archive.read_bytes()
    digest = sha256(data).hexdigest()
    require((directory / "SHA256SUMS").read_text(encoding="ascii") == f"{digest}  {archive.name}\n",
            "ZIP does not match the verified checksum")
    repository = os.environ["GITHUB_REPOSITORY"]
    descriptor = {
        "version": version,
        "target": manifest["target"],
        "sourceCommit": commit,
        "sourceDirty": False,
        "decoderCommit": "",
        "archive": {
            "fileName": archive.name,
            "sizeBytes": len(data),
            "sha256": digest,
            "url": f"https://github.com/{repository}/releases/download/{tag}/{archive.name}",
        },
    }
    public_key = ROOT / "release-public-key.pem"
    require(public_key.is_file(), "Provision this pack's Ed25519 release-public-key.pem before releasing")
    with TemporaryDirectory(prefix="goodtype-release-") as temporary:
        tmp = Path(temporary)
        secret = tmp / "key.pem"
        fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(os.environ["ADDON_SIGNING_KEY"])
        output = tmp / "content-update.json"
        output.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
        signature = output.with_suffix(".json.sig")
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(secret),
                        "-in", str(output), "-out", str(signature)], check=True)
        require(signature.stat().st_size == 64, "Unexpected Ed25519 signature length")
        subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key),
                        "-in", str(output), "-sigfile", str(signature)], check=True)
        for file in (output, signature):
            (directory / file.name).write_bytes(file.read_bytes())


if __name__ == "__main__":
    sign(Path("release-assets"))

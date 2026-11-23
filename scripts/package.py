"""Build a reproducible Windows x64 ZIP and checksum from the validated inventory."""
from hashlib import sha256
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from validate import ROOT, validate

PACKAGE_NAME = "Goodtype-Study-Templates"


def package():
    manifest, inventory = validate()
    # The ZIP name is a release identity and must not depend on the checkout directory.
    name = f"{PACKAGE_NAME}-{manifest['version']}-windows-x64"
    output = ROOT / "target/package"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{name}.zip"
    temp = archive.with_suffix(".zip.tmp")
    try:
        with ZipFile(temp, "w", compression=ZIP_STORED) as package:
            for relative, path in sorted(inventory.items()):
                entry = ZipInfo(f"{name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                package.writestr(entry, path.read_bytes())
        temp.replace(archive)
    finally:
        temp.unlink(missing_ok=True)
    digest = sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_bytes(f"{digest}  {archive.name}\n".encode("ascii"))
    print(f"{archive.name}  sha256 {digest}")
    return archive


if __name__ == "__main__":
    package()

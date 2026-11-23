# Building and releasing

Use Python 3.12 or newer.

```sh
python scripts/validate.py
python -m unittest discover -s scripts
python scripts/package.py
python -m pip install pymupdf
python scripts/preview.py
```

Packaging uses the manifest inventory, a fixed ZIP timestamp and a stable
entry order. The ZIP and SHA256SUMS are under `target/package/`. Contact
sheets are under `target/preview/`; the store image is `docs/preview.png`.
The runtime package contains only the manifest and the content files.
The validator covers shapes, page templates and palettes. Theme and Typst
package payloads need additional validators before being added here.

## Signing

Provision an independent Ed25519 release public key for this pack at
`release-public-key.pem`, using standard PEM public-key format. Configure the
matching private PEM as `ADDON_SIGNING_KEY` in the protected `release`
environment. The catalog must carry the same public key.

A `v<manifest version>` tag on a commit reachable from `main` triggers Windows
validation and packaging. The publisher signs the descriptor containing the
ZIP filename, size and SHA-256, verifies the 64-byte signature against the
checked-in public key, then publishes the ZIP, checksum and signed descriptor.
The descriptor assets are `content-update.json` and `content-update.json.sig`.
Their names must match the catalog and registry's content-pack integration
before the first published release.

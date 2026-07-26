# Hebcal data

`corpus-v1` is the immutable, checksummed location-independent Hebcal corpus
for Hebrew years 1 through 6000. Its Parquet files are one-time core data, not
build caches.

After `corpus-v1/manifest.json` exists:

- never edit, replace, or add a core partition;
- verify local copies against the manifests;
- publish corrections as a new corpus version;
- put evolving transformations and model-ready outputs outside the immutable
  corpus directory.

Population and validation tooling lives under `scripts/hebcal`.

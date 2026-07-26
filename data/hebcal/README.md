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

Two separate one-time, immutable Power BI boundaries may be materialized from
the finalized corpus:

- `powerbi-v1` contains the schedule and event projection;
- `powerbi-readings-v1` contains the seven normalized Parasha and leyning
  tables.

Neither directory is a build cache, neither should participate in scheduled
refresh after its initial import, and neither may be regenerated or
overwritten after landing. Changed transformations or added data types use a
new versioned directory. The readings boundary does not modify `powerbi-v1`.

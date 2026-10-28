export const backupPreview = {
  compatible: true,
  legacy: false,
  source_version: "3.4.1",
  installed_version: "3.4.1",
  created_at: 1792742400,
  schema_version: 8,
  installed_schema_version: 8,
  archive_sha256: "a".repeat(64),
  components: [
    { name: "db.sqlite", size_bytes: 24576, restored: true },
    { name: "config.yaml", size_bytes: 400, restored: true },
    { name: "config.py", size_bytes: 200, restored: false },
    { name: "app.tar.gz", size_bytes: 400000, restored: false },
  ],
  counts: { admin: 1, base_station: 1, rover: 3 },
  warnings: [],
  reasons: [],
};

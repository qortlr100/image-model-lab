# Contracts

Durable JSON shapes that outlive the code that wrote them: manifests stored on
NAS, execution protocol payloads and the artifact references embedded in both.

- `schemas/` holds one JSON Schema per shape and version.
- `examples/` holds one fixture per schema. A fixture is checked against its
  schema by tests, and the code that produces the shape is checked against the
  same fixture, so schema, example and implementation cannot drift apart
  silently.

## Versioning

- A file name carries its version: `<name>-v<major>.schema.json`.
- `schema_version` is a required field inside every instance. A reader that
  cannot recognise the version refuses the payload instead of guessing.
- A breaking change adds a new version file rather than editing the old one.
  Readers accept the current version and at least one preceding version while
  stored payloads are migrated.
- Additive, optional-only changes may edit the current version in place.

The API OpenAPI document is generated from the service and is not stored here;
it is the source for the generated TypeScript client.

| Schema | Written by |
|---|---|
| `artifact-reference-v1` | `image_model_lab_domain.artifacts.ArtifactReference` |

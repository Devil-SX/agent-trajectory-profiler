# <Ecosystem Name> Ecosystem Profile

Ecosystem ID: `<ecosystem_id>`  
Parser: `<parser module path>`  
Adapter: `<adapter class>`

## 1. Source Discovery

- Default root: `<path>`
- Discovery rule (glob): `<pattern>`
- Exclusions: `<if any>`
- Implementation entry: `<function name>`

## 2. Session Identity Model

- Physical session ID strategy: `<filename|event field|composite>`
- Logical session strategy: `<rules>`
- Parent/root lineage fields: `<keys>`
- Manifest reference: `agent_vis/parsers/manifests/<ecosystem_id>.json`

## 3. Raw Event Shapes

List accepted top-level event kinds and notable subtypes.

## 4. Mapping to Canonical and Unified Model

### Raw -> CanonicalEvent

- `event_kind`: `<rule>`
- `timestamp`: `<rule>`
- `actor`: `<rule>`
- `payload`: `<rule>`

### CanonicalEvent -> MessageRecord

Provide a mapping table from source event/subtype to unified message model output.

## 5. Fallback and Error Handling

- malformed JSON behavior
- missing timestamp behavior
- missing token field behavior
- unknown tool error behavior

All fallback behavior must match the ecosystem capability manifest.

## 6. Known Limitations

List known data-quality caveats, unsupported features, and confidence notes.

## 7. Validation Checklist

- [ ] Parser tests updated (`tests/test_*parser*.py`)
- [ ] API integration tests updated (`tests/test_api_integration.py`)
- [ ] Manifest added/updated (`agent_vis/parsers/manifests/*.json`)
- [ ] Capability docs updated (`docs/standards/*capability*`)
- [ ] Query/export compatibility reviewed (`docs/standards/query-export-contract.md`)

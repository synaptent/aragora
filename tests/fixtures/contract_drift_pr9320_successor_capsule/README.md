# PR #9320 successor backfill capsule (immutable release 377250950)

Byte-exact assets of the published successor capsule release
`backfill-v2-0b28f68b9f4d204ae14814169093723ea84c1364` (tag target
`fe97dc28cd5eb69eb05f1c634f406c021e92358c`, `immutable: true`, release API id
`377250950`; asset ids 530996282 / 530996294 / 530996270).

| asset | bytes | sha256 |
| --- | --- | --- |
| manifest.json | 457 | d4fc15a63da2bbc9e3d6380033431d0e829265c692e04de2fbadea9745afb259 |
| payload.json | 1122045 | 0c2f40b475c32ab489da1d91d0e1cc0c0b6cc0cc626d4044aa70cd6b4c237311 |
| checksums.txt | 159 | 9f0990298f6e51d8d6af77d57fdfa25d5605d4f6fcbfc64f96480af753fcdef2 |

`tests/scripts/test_contract_drift_sequence.py` authenticates these bytes
against the pinned digests before reading any capsule plane; do not edit them.

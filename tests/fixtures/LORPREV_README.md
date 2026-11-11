# Sanitized XML fixtures

The committed `.loredit` and `.lorprev` fixtures are plain XML so reviewers, diffs,
secret scanning, and CI can inspect the actual content. Fixture names, identifiers,
and media/background references are synthetic or removed. No audio, personal
sequences, local workstation paths, or background image files belong here.

The large Revision 1 and Revision 56 exports are retained as readable XML rather
than opaque base64/gzip wrappers. The compact native sequence fixture keeps
representative effects for semantic round-trip tests; the independent preview
is extracted from the same template for integration tests.

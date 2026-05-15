"""Stage 2 multi-pass prompt builders.

Each pass lives in its own module:

- :mod:`pass_0_outline` — Pass 0 (scene outline + act-tags)
- :mod:`pass_1_digest_single` — Pass 1 single-call digest
- :mod:`pass_1_digest_chunked` — Pass 1 act-chunked digest
- :mod:`pass_2_story` — Pass 2 story script prompt
- :mod:`post_validate` — deterministic ref validation

Shared helpers live in :mod:`timeline` and :mod:`scene_markers`.
"""

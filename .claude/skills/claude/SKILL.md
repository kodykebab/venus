---
name: claude
description: Use when changing ParaCheck's Claude synthesis, API-key handling, review fallback rendering, or related tests and documentation.
---

# Claude Review Workflow

Use this skill for work involving the optional Anthropic integration. ParaCheck
must remain useful when no API key is configured: raw findings should still be
rendered, while a configured key adds a written, prioritised synthesis.

## Workflow

1. Trace the request from the CLI or service entry point to the synthesis call
	and final report renderer before editing.
2. Preserve the fallback path. Missing, invalid, or unavailable credentials
	must not prevent raw findings from being returned.
3. Keep credentials out of logs, subprocess arguments, generated reports, and
	checked-in files. Existing environment variables should take precedence over
	values loaded from `.env`.
4. When changing service credentials, verify encryption, validation, masking,
	removal, and the installation or dashboard flow together.
5. Update the nearest user-facing documentation when configuration or billing
	behavior changes.

## Validation

- Run `analyzer/.venv/bin/python -m pytest -q service/test_service.py` for
  service changes.
- Run `cd analyzer && npm test && npm run build` for analyzer changes.
- Run the focused static or Foundry tests when detector or contract behavior
  changes and the required local tools are available.
- Include a no-key case whenever synthesis behavior changes.
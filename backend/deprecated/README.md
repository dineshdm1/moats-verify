# Deprecated Modules

This folder stores legacy modules moved during the Moats Verify refactor.
They are retained temporarily to provide a rollback path during migration.

Current contents:
- verify/: legacy verification pipeline (claim extractor, dual retrieval, contradiction detector, verdict generator)

Do not add new runtime dependencies on these modules.

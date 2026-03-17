Agent Guidelines

- Purpose: provide rules for automated code-editing agents working in this repository.

- Do NOT use broad or excessive `try/except` blocks in our own application code. Use exception handling sparingly and only when:
  - Interacting with external systems (network, filesystem, OS clipboard, system commands, third-party CLIs), or
  - Working around platform-specific APIs where a known, limited set of exceptions may be raised.

- When catching exceptions:
  - Catch the most specific exception type possible (e.g., `httpx.HTTPError`, `OSError`, `FletUnsupportedPlatformException`).
  - Avoid bare `except:` or `except Exception:` around large blocks of logic.
  - Do not suppress exceptions silently; log them with context and either handle them or surface an appropriate error to the user.

- Code changes by agents should prefer small, targeted try/except blocks around the risky call only, not entire functions.

- Async APIs:
  - Await coroutines properly (e.g., use `page.run_task(...)` for Flet async clipboard calls). Do not leave coroutines unawaited.

- Fallbacks:
  - Provide explicit, minimal fallbacks for platform-limited features (e.g., clipboard `set_image`). Implement a single, clear fallback path rather than multiple nested fallbacks.

- Review:
  - When making edits that change error-handling behavior, ensure unit tests still pass and add a brief comment in the PR describing the rationale.

These rules are authoritative for any automated agent editing this repository. If an agent cannot follow them due to technical constraints, it must pause and ask the repository maintainer for guidance.

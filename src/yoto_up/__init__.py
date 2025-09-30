"""yoto_up package initializer.

This module provides a small compatibility shim so legacy code that imports
top-level modules (for example `import models` or `import waveform_utils`)
continues to work after the project was moved under the `yoto_up` package.

It imports the common submodules under `yoto_up.*` and inserts them into
`sys.modules` under their legacy names. This keeps the change backwards-
compatible while allowing setuptools to install a single package.
"""
from __future__ import annotations

import importlib
import sys

__all__ = [
	"yoto",
	"gui",
	"models",
	"yoto_api",
	"tui",
	"icons",
	"waveform_utils",
	"audio_adjust_utils",
	"pixel_art_editor_rich",
]

# Try to import and register a few legacy top-level module names so code which
# does `import models` or `from waveform_utils import ...` keeps working.
_legacy_modules = [
	"models",
	"gui",
	"yoto_api",
	"tui",
	"icons",
	"waveform_utils",
	"audio_adjust_utils",
	"pixel_art_editor_rich",
	"yoto",
]

for _name in _legacy_modules:
	pkg_name = f"yoto_up.{_name}"
	if _name in sys.modules:
		# prefer an existing top-level module (rare)
		continue
	try:
		mod = importlib.import_module(pkg_name)
		# expose under the legacy top-level name
		sys.modules[_name] = mod  # type: ignore[index]
	except Exception:
		# If the submodule fails to import (missing optional deps etc.) we
		# swallow the error here to avoid breaking simple imports. The error
		# will be raised later when the functionality is actually used.
		pass

"""yoto_up package initializer.

This module provides a small compatibility shim so legacy code that imports
top-level modules (for example `import models` or `import waveform_utils`)
continues to work after the project was moved under the `yoto_up` package.

It imports the common submodules under `yoto_up.*` and inserts them into
`sys.modules` under their legacy names. This keeps the change backwards-
compatible while allowing setuptools to install a single package.
"""
from __future__ import annotations

#import importlib
#import sys
#from types import ModuleType
#
#__all__ = [
#	"yoto",
#	"gui",
#	"models",
#	"yoto_api",
#	"tui",
#	"icons",
#	"waveform_utils",
#	"audio_adjust_utils",
#	"pixel_art_editor_rich",
#]
#
## Provide a lazy compatibility shim for legacy top-level module names.
## Many modules in the codebase historically did `import models` or
## `from waveform_utils import ...`. After moving everything into the
## `yoto_up` package we register lightweight proxy modules under the old
## names which import the real `yoto_up.*` submodules on first use.
#_legacy_modules = [
#	"models",
#	"gui",
#	"yoto_api",
#	"tui",
#	"icons",
#	"waveform_utils",
#	"audio_adjust_utils",
#	"pixel_art_editor_rich",
#	"yoto",
#]
#
#class _LazyModule(ModuleType):
#	def __init__(self, legacy_name: str, pkg_name: str):
#		super().__init__(legacy_name)
#		self.__legacy_name = legacy_name
#		self.__pkg_name = pkg_name
#		self.__loaded = False
#
#	def _load(self):
#		if self.__loaded:
#			return
#		real = importlib.import_module(self.__pkg_name)
#		# Replace proxy in sys.modules with the real module
#		sys.modules[self.__legacy_name] = real
#		# copy attributes so any references to the proxy continue to work
#		for k, v in vars(real).items():
#			try:
#				setattr(self, k, v)
#			except Exception:
#				pass
#		self.__loaded = True
#
#	def __getattr__(self, name: str):
#		# Load the real module on first attribute access
#		self._load()
#		return getattr(sys.modules[self.__legacy_name], name)
#
#	def __dir__(self):
#		self._load()
#		return dir(sys.modules[self.__legacy_name])
#
#
#for _name in _legacy_modules:
#	if _name in sys.modules:
#		continue
#	pkg_name = f"yoto_up.{_name}"
#	try:
#		real = importlib.import_module(pkg_name)
#	except Exception:
#		# create a lazy proxy which will import on first use
#		proxy = _LazyModule(_name, pkg_name)
#		sys.modules[_name] = proxy
#	else:
#		# module imported successfully — expose it under the legacy name
#		sys.modules[_name] = real
#
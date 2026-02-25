import json
import os
import threading
import atexit
from pathlib import Path
from typing import Any, Optional


def _default_state_path() -> Path:
    xdg = os.getenv('XDG_CONFIG_HOME')
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / '.config'
    return (base / 'yoto-up' / 'ui_state.json')


class UIState:
    """A simple threadsafe UI state persistence helper.

    Usage:
      from yoto_up.ui_state import state
      state.set('main_window', 'size', (800, 600))
      state.get('main_window', 'size', default=(640, 480))
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _default_state_path()
        self._lock = threading.RLock()
        self._data = {}
        self._ensure_dir()
        self._load()
        atexit.register(self.save)

    def _ensure_dir(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            with self._path.open('r', encoding='utf-8') as f:
                self._data = json.load(f)
        except Exception:
            # if anything goes wrong, start fresh
            self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self._path.with_suffix('.tmp')
                with tmp.open('w', encoding='utf-8') as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                tmp.replace(self._path)
            except Exception:
                # best-effort only
                return

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Set a value under a namespace and persist immediately."""
        with self._lock:
            ns = self._data.setdefault(namespace, {})
            ns[key] = value
            self.save()

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(namespace, {}).get(key, default)

    def delete(self, namespace: str, key: str) -> None:
        with self._lock:
            ns = self._data.get(namespace)
            if not ns:
                return
            ns.pop(key, None)
            self.save()

    def to_dict(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))


# module-level singleton for easy imports from anywhere
state = UIState()


# convenience functions
def set_state(namespace: str, key: str, value: Any) -> None:
    state.set(namespace, key, value)


def get_state(namespace: str, key: str, default: Any = None) -> Any:
    return state.get(namespace, key, default)


def delete_state(namespace: str, key: str) -> None:
    state.delete(namespace, key)


def save_state() -> None:
    state.save()


def get_state_path() -> Path:
    """Return the path to the UI state file used by the singleton."""
    return state._path


def remove_state_file() -> None:
    """Remove the persisted UI state file (best-effort) and clear in-memory data."""
    try:
        with state._lock:
            state._data = {}
            try:
                if state._path.exists():
                    state._path.unlink()
            except Exception:
                pass
    except Exception:
        pass

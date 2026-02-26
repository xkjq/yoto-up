from typing import Any, Optional, Iterable, Mapping


class Control:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


class Text(Control):
    def __init__(self, content: Any = None, *args: Any, **kwargs: Any) -> None: ...


class Column(Control):
    def __init__(self, *controls: Any, **kwargs: Any) -> None: ...


class Row(Control):
    def __init__(self, *controls: Any, **kwargs: Any) -> None: ...


class ElevatedButton(Control):
    def __init__(self, text: Any = None, *, on_click: Any = None, **kwargs: Any) -> None: ...


class Image(Control):
    def __init__(self, src: Any = None, **kwargs: Any) -> None: ...


class Icon(Control):
    def __init__(self, icon: Any = None, **kwargs: Any) -> None: ...


class Page(Control):
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


def alert(*args: Any, **kwargs: Any) -> None: ...

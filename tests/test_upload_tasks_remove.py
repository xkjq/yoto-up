import pytest
import types


def _make_fake_ft(monkeypatch):
    """Monkeypatch minimal flet controls used by FileUploadRow with lightweight fakes."""
    fake_ft = types.SimpleNamespace()

    class FakeControl:
        def __init__(self, *args, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class FakeRow(FakeControl):
        def __init__(self, controls=None, **kwargs):
            super().__init__(**kwargs)
            self.controls = list(controls or [])

    class FakeContainer(FakeControl):
        def __init__(self, content=None, padding=None, **kwargs):
            super().__init__(**kwargs)
            self.content = content

    class FakeTextButton(FakeControl):
        def __init__(self, content=None, on_click=None, **kwargs):
            super().__init__(**kwargs)
            self.content = content
            self.on_click = on_click

    # Expose minimal attributes used by upload_tasks
    fake_ft.Text = FakeControl
    fake_ft.ProgressBar = FakeControl
    fake_ft.ProgressRing = FakeControl
    fake_ft.TextButton = FakeTextButton
    fake_ft.Row = FakeRow
    fake_ft.Container = FakeContainer
    fake_ft.Column = lambda controls=None, **_: types.SimpleNamespace(controls=list(controls or []))

    # Monkeypatch the imported flet module in the upload_tasks namespace
    import yoto_up.yoto_app.upload_tasks as ut
    monkeypatch.setattr(ut, 'ft', fake_ft)
    return fake_ft


def test_file_upload_row_remove(monkeypatch):
    # Patch flet to lightweight substitutes
    fake_ft = _make_fake_ft(monkeypatch)

    # Import after monkeypatching ft inside module
    from yoto_up.yoto_app.upload_tasks import FileUploadRow

    class DummyPage:
        def __init__(self):
            self.file_rows_column = types.SimpleNamespace(controls=[])
            self.updated = False

        def update(self):
            self.updated = True

    page = DummyPage()

    # Create two rows and append their container rows to the column (normal UI flow)
    row1 = FileUploadRow("/tmp/a.mp3", page)
    row2 = FileUploadRow("/tmp/b.mp3", page)

    page.file_rows_column.controls.append(row1.row)
    page.file_rows_column.controls.append(row2.row)

    # Removing should remove the actual container for row1
    row1.on_remove()

    assert row1.row not in page.file_rows_column.controls
    assert row2.row in page.file_rows_column.controls
    assert page.updated is True

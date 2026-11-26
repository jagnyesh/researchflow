"""
Regression test for the Streamlit AppTest SHUTDOWN race (flaky Linux CI).

Main run 45089260648 (commit c905b87) failed on ubuntu-latest with
``KeyError: 'client_state'`` inside ``AppTest._run``, in
``test_view_details_makes_download_ui_reachable``; macOS and the previous
run passed.

Cause, in streamlit 1.51.0 (and still in 1.67.0): ``LocalScriptRunner`` records
each event in two steps on the script thread, ``events.append(event)`` and then
``event_data.append(kwargs)``. The test thread polls ``script_stopped()``,
which looks only at ``events``. If it sees SHUTDOWN between the two appends,
``AppTest._run`` reads ``event_data[-1]``, which is still the previous event's
kwargs (no ``client_state``), and raises KeyError.

The test below widens that gap on purpose, so it fails every time without the
guard in ``tests/conftest.py`` and passes with it.
"""

import time

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import local_script_runner


class _SlowShutdownData(list):
    """event_data list that delays recording SHUTDOWN's kwargs."""

    def append(self, item):
        if isinstance(item, dict) and "client_state" in item:
            time.sleep(0.05)
        super().append(item)


def test_apptest_waits_for_shutdown_data(tmp_path, monkeypatch):
    original_init = local_script_runner.LocalScriptRunner.__init__

    def init_with_slow_data(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.event_data = _SlowShutdownData()

    monkeypatch.setattr(local_script_runner.LocalScriptRunner, "__init__", init_with_slow_data)

    script = tmp_path / "app.py"
    script.write_text("import streamlit as st\nst.text_input('Name', key='name')\n")

    at = AppTest.from_file(str(script)).run()
    at.text_input(key="name").set_value("Jane").run()

    assert at.text_input(key="name").value == "Jane"

"""Tests for the homepage."""

from streamlit.testing.v1 import AppTest


def test_app_opens_on_overview():
    app = AppTest.from_file("../app.py", default_timeout=30).run()

    assert not app.exception
    assert app.title[0].value == "Pleasant Rides"
    assert [block.value for block in app.subheader] == ["Enjoyable", "Easy", "Safe"]

import re

import mihenk


def test_version_is_semantic() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", mihenk.__version__)

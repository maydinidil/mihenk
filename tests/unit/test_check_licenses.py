import pytest

from tools.check_licenses import ALLOWED, spdx_allowed


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("MIT", True),
        ("Apache-2.0", True),
        ("MIT OR GPL-3.0-only", True),
        ("MIT AND GPL-3.0-only", False),
        ("(MIT OR Apache-2.0) AND BSD-3-Clause", True),
        ("LGPL-2.1-or-later", False),
        ("GPL-2.0-or-later WITH Classpath-exception-2.0", False),
        ("MPL-2.0", True),
        ("LicenseRef-Proprietary", False),
    ],
)
def test_spdx_expressions(expression: str, expected: bool) -> None:
    assert spdx_allowed(expression, ALLOWED) is expected


def test_malformed_expression_is_an_error() -> None:
    with pytest.raises(ValueError, match="licence expression"):
        spdx_allowed("MIT OR", ALLOWED)

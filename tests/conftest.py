from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fx():
    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load


@pytest.fixture
def fx_gz():
    from isnad.build import read_page

    def load(name: str) -> str:
        return read_page(FIXTURES / name)

    return load

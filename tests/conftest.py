"""Fixtures compartidos de tests -- nunca escriben en data/ real."""
import pytest

import ratings_store


@pytest.fixture
def ratings_tmp(tmp_path, monkeypatch):
    """Redirige el almacenamiento de ratings a un tmp_path para que
    ningun test toque data/ratings_propios.json."""
    monkeypatch.setattr(ratings_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ratings_store, "ARCHIVO_RATINGS",
                        tmp_path / "ratings_propios.json")
    return tmp_path / "ratings_propios.json"

from __future__ import annotations

from io import StringIO

import pytest

from mne_lsl.utils.config import _get_gpu_info, sys_info


def test_sys_info() -> None:
    """Test info-showing utility."""
    out = StringIO()
    sys_info(fid=out)
    value = out.getvalue()
    out.close()
    assert "Platform:" in value
    assert "Executable:" in value
    assert "CPU:" in value
    assert "Physical cores:" in value
    assert "Logical cores" in value
    assert "RAM:" in value
    assert "SWAP:" in value

    assert "numpy" in value
    assert "psutil" in value

    assert "style" not in value
    assert "test" not in value

    out = StringIO()
    sys_info(fid=out, developer=True)
    value = out.getvalue()
    out.close()

    assert "build" in value
    assert "style" in value
    assert "test" in value


def test_gpu_info() -> None:
    """Test getting GPU info."""
    pytest.importorskip("pyvista")
    version, renderer = _get_gpu_info()
    assert version is not None
    assert renderer is not None

from __future__ import annotations

import uuid

import pytest

from mne_lsl.lsl import (
    StreamInfo,
    StreamOutlet,
    library_version,
    local_clock,
    protocol_version,
    resolve_streams,
)
from mne_lsl.lsl.load_liblsl import _VERSION_MIN, _VERSION_PROTOCOL


def test_library_version() -> None:
    """Test retrieval of library version."""
    version = library_version()
    assert isinstance(version, int)
    assert _VERSION_MIN <= version


def test_protocol_version() -> None:
    """Test retrieval of protocol version."""
    version = protocol_version()
    assert isinstance(version, int)
    assert version == _VERSION_PROTOCOL


def test_local_clock() -> None:
    """Test retrieval of local (client) LSL clock."""
    ts = local_clock()
    assert isinstance(ts, float)
    assert ts >= 0
    assert local_clock() >= ts


@pytest.mark.xfail(reason="Fails if streams are present in the background.")
@pytest.mark.slow
def test_resolve_streams() -> None:
    """Test detection of streams on the network."""
    streams = resolve_streams(timeout=0.1)
    assert isinstance(streams, list)
    assert len(streams) == 0

    # detect all streams
    sinfo = StreamInfo("test", "", 1, 0.0, "int8", uuid.uuid4().hex)
    outlet = StreamOutlet(sinfo)
    streams = resolve_streams(timeout=2)
    assert isinstance(streams, list)
    assert len(streams) == 1
    assert streams[0] == sinfo
    del outlet

    # detect streams by properties
    sinfo1 = StreamInfo("test1", "", 1, 0.0, "int8", "")
    sinfo2 = StreamInfo("test1", "Markers", 1, 0, "int8", "")
    sinfo3 = StreamInfo("test2", "", 1, 0.0, "int8", "")

    outlet1 = StreamOutlet(sinfo1)  # noqa: F841
    outlet2 = StreamOutlet(sinfo2)  # noqa: F841
    outlet3 = StreamOutlet(sinfo3)  # noqa: F841

    streams = resolve_streams(timeout=2)
    assert len(streams) == 3
    assert sinfo1 in streams
    assert sinfo2 in streams
    assert sinfo3 in streams

    streams = resolve_streams(name="test1", minimum=2, timeout=2)
    assert len(streams) == 2
    assert sinfo1 in streams
    assert sinfo2 in streams

    streams = resolve_streams(name="test1", minimum=1, timeout=2)
    assert len(streams) in (1, 2)

    streams = resolve_streams(stype="Markers")
    assert len(streams) == 1
    assert sinfo2 in streams

    streams = resolve_streams(name="test2", minimum=2, timeout=2)
    assert len(streams) == 1
    assert sinfo3 in streams

    streams = resolve_streams(name="test1", stype="Markers", timeout=2)
    assert len(streams) == 1
    assert sinfo2 in streams

    with pytest.raises(
        ValueError, match="'timeout' must be a strictly positive integer"
    ):
        resolve_streams(timeout=-1)
    with pytest.raises(
        ValueError, match="'minimum' must be a strictly positive integer"
    ):
        resolve_streams(name="test", minimum=-1)

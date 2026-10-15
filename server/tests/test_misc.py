import pytest

from rekamind_server import jobs
from rekamind_server.bench import wer
from rekamind_server.config import Settings
from rekamind_server.db import init_db, make_engine, make_session_factory
from rekamind_server.engines.registry import build_engines
from rekamind_server.models import Meeting
from rekamind_server.schemas import parse_clock


def test_wer():
    assert wer("a b c d", "a b c d") == 0
    assert wer("a b c d", "a x c") == pytest.approx(0.5)  # 1 substitution + 1 deletion
    assert wer("Halo, Dunia!", "halo dunia") == 0  # case and punctuation are ignored
    assert wer("", "x") == 1.0


@pytest.mark.parametrize("s,ms", [("05:30", 330_000), ("[01:02:03]", 3_723_000), ("0:05", 5000),
                                  ("abc", None), (None, None)])
def test_parse_clock(s, ms):
    assert parse_clock(s) == ms


def test_registry_modes():
    assert build_engines(Settings(engines="none")) is None
    assert build_engines(Settings(engines="fake")) is not None
    with pytest.raises(ValueError):
        build_engines(Settings(engines="mystery"))


async def test_job_that_keeps_killing_the_worker_is_failed_not_retried_forever():
    e = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(e)
    sf = make_session_factory(e)
    async with sf() as s:
        s.add(Meeting(id="b" * 32, title="x"))
        await s.commit()
    await jobs.enqueue(sf, "b" * 32)
    for _ in range(jobs.MAX_ATTEMPTS):
        assert await jobs.claim_next(sf) is not None  # claimed, then "process died"
        await jobs.recover_abandoned(sf) if _ < jobs.MAX_ATTEMPTS - 1 else None
    assert await jobs.recover_abandoned(sf) == 0
    async with sf() as s:
        m = await s.get(Meeting, "b" * 32)
        assert m.status == "failed" and "berhenti tiba-tiba" in m.error


def test_demo_engines_produce_realistic_content(tmp_path):
    from rekamind_server.engines.registry import build_engines

    e = build_engines(Settings(engines="demo"))
    assert e is not None and e.description["extractor"] == "demo"
    mic = e.transcriber.transcribe(tmp_path / "mic.wav", "id")
    assert len(mic) >= 3 and all(s.end_ms > s.start_ms for s in mic)
    assert e.diarizer.diarize(tmp_path / "speaker.wav")


def test_prebuilt_image_compose_files_stay_in_sync():
    """The CPU and GPU paste-into-Portainer files must expose the same settings; only image tag, device and GPU reservation differ."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    cpu = yaml.safe_load((root / "docker-compose.image.yml").read_text())["services"]["rekamind"]
    gpu = yaml.safe_load((root / "docker-compose.image-gpu.yml").read_text())["services"]["rekamind"]
    assert set(cpu["environment"]) == set(gpu["environment"])
    assert cpu["image"].endswith("-cpu}") and gpu["image"].endswith("-cuda}")
    assert gpu["environment"]["REKAMIND_WHISPER_DEVICE"] == "cuda" and cpu["environment"]["REKAMIND_WHISPER_DEVICE"] == "cpu"
    assert gpu["deploy"]["resources"]["reservations"]["devices"][0]["driver"] == "nvidia"

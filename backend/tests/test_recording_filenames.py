"""Readable names, exclusive concurrent reservations and original preservation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from app.engine.pipeline.ytdlp import YtdlpLivePipeline

@pytest.mark.parametrize('suffix',['.ts','.ts.part','.native.mp4','.native.mp4.part','.native.ts','.native.mkv','.mkv','.mp4','.jpg','.ts.audio1','.ts.audio1.part','.native.mp4.audio1','.native.mp4.audio1.part'])
def test_existing_capture_family_is_never_overwritten(tmp_path,suffix):
    original=tmp_path/('한글 방송 제목'+suffix);original.write_bytes(b'preserved')
    selected=YtdlpLivePipeline._reserve_capture_file(tmp_path/'한글 방송 제목.ts')
    assert selected.name=='한글 방송 제목 (2).ts'
    assert original.read_bytes()==b'preserved'
    assert Path(str(selected)+'.part').is_file()

def test_concurrent_same_title_has_short_unique_names(tmp_path):
    base=tmp_path/'[채널] 방송 제목.ts'
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths=list(pool.map(lambda _:YtdlpLivePipeline._reserve_capture_file(base),range(8)))
    assert len(set(paths))==8
    assert {p.name for p in paths}=={'[채널] 방송 제목.ts',*(f'[채널] 방송 제목 ({i}).ts' for i in range(2,9))}
    assert all(Path(str(p)+'.part').is_file() for p in paths)
    assert not any(len(part)==32 for p in paths for part in p.stem.split())

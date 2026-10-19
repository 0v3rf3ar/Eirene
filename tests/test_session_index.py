"""The derived index tracks log changes without rescanning unchanged sessions."""
from eirene.core import paths, session_index
from eirene.core.session import Session, list_sessions


def test_warm_index_avoids_reparsing_logs(workdir, monkeypatch):
    session = Session.create(workdir)
    session.add_user('Original task')
    scans=[]
    original = session_index._scan
    def scan(path, stat):
        scans.append(path)
        return original(path,stat)
    monkeypatch.setattr(session_index,'_scan',scan)
    assert list_sessions()[0]['name'] == 'Original task'
    assert list_sessions()[0]['name'] == 'Original task'
    assert len(scans) == 1
    session.rename('Renamed task')
    assert list_sessions()[0]['name'] == 'Renamed task'
    assert len(scans) == 2
    session.clear()
    assert list_sessions() == []


def test_corrupt_cache_falls_back_to_logs(workdir):
    session = Session.create(workdir)
    session.add_user('Keep this conversation')
    session.close()
    (paths.home()/'session-index.sqlite3').write_bytes(b'corrupt SQLite file')
    assert list_sessions()[0]['id'] == session.id


def test_index_notices_external_replacement(workdir):
    session = Session.create(workdir)
    session.add_user('First')
    session.close()
    assert list_sessions()[0]['turns'] == 1
    session.path.write_text(session.path.read_text()+'{"t":"user","content":"Second"}\n')
    assert list_sessions()[0]['turns'] == 2

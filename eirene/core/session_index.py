"""Rebuildable metadata cache; JSONL session logs remain authoritative."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from . import paths
from .errors import SessionError


def _scan(path, stat):
    from .session import name_from, read_records
    info = dict(id=path.stem, path=str(path), mtime=stat.st_mtime,
                sandbox='', name='', turns=0, parent_id='', agent='', status='saved', links=[])
    for record in read_records(path):
        kind = record.get('t')
        if kind == 'meta':
            info['sandbox'] = record.get('sandbox', '')
            info['name'] = record.get('name') or ''
        elif kind == 'rename' and record.get('name'):
            info['name'] = str(record['name'])
        elif kind == 'user':
            info['turns'] += 1
            if not info['name']:
                info['name'] = name_from(str(record.get('content', '')))
        elif kind == 'delegation':
            info.update(parent_id=record.get('parent_id', ''), agent=record.get('agent', ''),
                        status=record.get('status', 'saved'))
        elif kind == 'delegation_status':
            info['status'] = record.get('status', 'saved')
        elif kind == 'tool_result' and record.get('name') == 'delegate_tasks':
            try:
                reports = json.loads(record.get('content', ''))
            except (ValueError, TypeError):
                continue
            if isinstance(reports, list):
                info['links'].extend({key: report.get(key, '') for key in ('session_id','agent','status')}
                                     for report in reports if isinstance(report, dict) and report.get('session_id'))
    info['name'] = info['name'] or 'untitled'
    return info


def _files():
    result = []
    for path in paths.sessions_dir().glob('*.jsonl'):
        try:
            result.append((path, path.stat()))
        except OSError:
            continue
    return sorted(result, key=lambda item: (item[1].st_mtime_ns, item[0].name), reverse=True)


def _read(files, connection=None):
    out = []
    for path, stat in files:
        signature = f'{stat.st_mtime_ns}:{stat.st_ctime_ns}:{stat.st_size}'
        cached = connection.execute('SELECT signature, info FROM sessions WHERE path=?', (str(path),)).fetchone() if connection else None
        if cached and cached[0] == signature:
            info = json.loads(cached[1])
        else:
            try:
                info = _scan(path, stat)
            except SessionError:
                continue
            if connection:
                connection.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)',
                                   (str(path), signature, json.dumps(info)))
        out.append(info)
    if connection:
        live = {str(path) for path, _ in files}
        stale = [row[0] for row in connection.execute('SELECT path FROM sessions') if row[0] not in live]
        connection.executemany('DELETE FROM sessions WHERE path=?', ((path,) for path in stale))
    return out


def metadata():
    files = _files()
    if not files:
        return []
    database = paths.home() / 'session-index.sqlite3'
    try:
        with closing(sqlite3.connect(database, timeout=2)) as connection:
            database.chmod(0o600)
            with connection:
                connection.execute('CREATE TABLE IF NOT EXISTS sessions (path TEXT PRIMARY KEY, signature TEXT NOT NULL, info TEXT NOT NULL)')
                return _read(files, connection)
    except (sqlite3.Error, OSError, ValueError, TypeError):
        # An unavailable/corrupt cache must never hide a saved conversation.
        return _read(files)

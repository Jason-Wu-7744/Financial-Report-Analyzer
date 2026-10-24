"""Durable, per-research report jobs; API credentials stay in process memory."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def job_path(folder: Path, language: str) -> Path:
    return folder / ('deep-job.en.json' if language == 'en' else 'deep-job.json')


def read_job(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def active_job(job: dict) -> bool:
    return job.get('status') in {'queued', 'running'} and time.time() - float(job.get('heartbeat') or 0) < 120


def launch_job(root: Path, folder: Path, language: str, request: dict, api_key: str) -> dict:
    """Serialize launches across tabs and spawn a worker independent of the UI."""
    path = job_path(folder, language)
    lock = path.with_suffix('.lock')
    folder.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > 60:
            lock.unlink(missing_ok=True)
        return read_job(path)
    try:
        os.close(descriptor)
        existing = read_job(path)
        if active_job(existing):
            return existing
        token = uuid.uuid4().hex
        request_path = folder / ('deep-request-' + token + '.json')
        # Do not persist credentials or an arbitrary user-supplied root.
        safe_request = {k: v for k, v in request.items() if k not in {'api_key', 'root'}}
        safe_request.update(language=language, job_token=token)
        atomic_json(request_path, safe_request)
        job = {'token': token, 'status': 'queued', 'phase': 'queued', 'heartbeat': time.time(),
               'started_at': time.time(), 'completed': 0, 'total': len(request.get('chosen') or []), 'events': []}
        atomic_json(path, job)
        environment = os.environ.copy()
        environment['FILING_JOB_API_KEY'] = api_key
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        try:
            with (folder / 'deep-worker.log').open('a', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, str(root / 'job_worker.py'), str(request_path)],
                                           cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, **kwargs)
            return read_job(path)
        except Exception:
            job.update(status='failed', phase='launch_failed', heartbeat=time.time())
            atomic_json(path, job)
            raise
    finally:
        lock.unlink(missing_ok=True)

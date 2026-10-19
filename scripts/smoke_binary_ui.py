#!/usr/bin/env python3
"""Exercise typing /plugins, Esc, the plugin popup, and optional binary replacement."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def check(binary: Path, replacement: Path | None = None):
    if os.name == 'nt':
        print('PTY smoke test skipped on native Windows; popup tests cover key handling.')
        return
    import fcntl
    import pty
    import select
    import struct
    import termios
    with tempfile.TemporaryDirectory(prefix='eirene-ui-smoke-') as directory:
        root=Path(directory)
        workspace=root/'work'; workspace.mkdir()
        data=root/'data'; data.mkdir()
        (data/'config.json').write_text(json.dumps({'trusted_workspaces':[str(workspace)],
                                                  'reduce_motion':True,'notifications':False}))
        target=root/'eirene'
        shutil.copy2(binary,target)
        env=dict(os.environ,EIRENE_HOME=str(data),EIRENE_NO_UPDATE_CHECK='1',
                 EIRENE_REDUCE_MOTION='1',TERM='xterm-256color',NO_COLOR='1')
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',36,110,0,0))
        process=subprocess.Popen([str(target),'-C',str(workspace)],stdin=slave,stdout=slave,
                                 stderr=slave,cwd=workspace,env=env)
        os.close(slave)
        transcript=bytearray()
        def pump(seconds, allow_exit=False):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if select.select([master],[],[],min(.05,max(0,deadline-time.monotonic())))[0]:
                    try:
                        chunk=os.read(master,65536)
                    except OSError:
                        break
                    if not chunk: break
                    transcript.extend(chunk)
            if process.poll() is not None and (process.returncode or not allow_exit):
                raise RuntimeError(f'Frozen UI exited with {process.returncode}: {transcript[-3000:].decode(errors="replace")}')
        try:
            pump(3)
            os.write(master,b'/plugins')  # User typed it but has not submitted.
            pump(.4)
            if replacement is not None:
                next_binary=root/'next-binary'
                shutil.copy2(replacement,next_binary)
                os.replace(next_binary,target)
            os.write(master,b'\x1b')
            pump(.5)
            os.write(master,b'\r')  # Submit /plugins and open the floating catalog.
            pump(.6)
            deadline=time.monotonic()+5
            while b'ponytail' not in transcript and time.monotonic()<deadline:
                pump(.1)
            if b'ponytail' not in transcript:
                raise RuntimeError('Frozen plugin catalog did not open: '+transcript[-5000:].decode(errors='replace'))
            os.write(master,b'\x1b')
            pump(.5)
            os.write(master,b'\x04')
            pump(.5,allow_exit=True)
            process.wait(timeout=10)
            if process.returncode or b'Traceback' in transcript or b'zlib.error' in transcript:
                raise RuntimeError(f'Frozen UI failed: {transcript[-3000:].decode(errors="replace")}')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
    print('Frozen /plugins typing, Esc, popup dismissal, and exit passed'
          + (' after replacing the running executable.' if replacement else '.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary',type=Path)
    parser.add_argument('--replace-with',type=Path)
    args=parser.parse_args()
    check(args.binary.resolve(),args.replace_with.resolve() if args.replace_with else None)

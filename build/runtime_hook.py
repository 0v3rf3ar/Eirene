"""Keep lazy imports attached to the archive this process actually started with."""
import sys


def pin_archive(archive, executable, platform=sys.platform):
    import os
    filename = archive._filename
    if (platform.startswith('linux') and os.path.exists('/proc/self/exe')
            and os.path.abspath(filename) == os.path.abspath(executable)):
        # /proc/self/exe keeps referring to the original executable inode even
        # after an updater atomically replaces its pathname.
        archive._filename = '/proc/self/exe'
        return

    # Other systems lack that stable executable handle. Keep a private copy of
    # the PYZ and trailing data; its offsets are relative to the PYZ start.
    import atexit
    import shutil
    import tempfile
    descriptor, snapshot = tempfile.mkstemp(prefix='eirene-runtime-', suffix='.pyz')
    def cleanup():
        try:
            os.unlink(snapshot)
        except FileNotFoundError:
            pass
    try:
        with os.fdopen(descriptor, 'wb') as output, open(filename, 'rb') as source:
            source.seek(archive._start_offset)
            shutil.copyfileobj(source, output)
    except BaseException:
        cleanup()
        raise
    archive._filename = snapshot
    archive._start_offset = 0
    atexit.register(cleanup)


if getattr(sys, 'frozen', False):
    import pyimod02_importers
    pin_archive(pyimod02_importers.pyz_archive, sys.executable)

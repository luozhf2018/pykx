import operator
import os
from pathlib import Path
from platform import system
import re
import shutil
import site
import subprocess
import sys

# Do not import pykx here - use the `kx` fixture instead!
import pytest
import requests


# Decorator for tests that may damage the environment they are run in, and thus should only be run
# in disposable environments such as within Docker containers in CI. GitLab Runners provides the
# env var we check for: https://docs.gitlab.com/ee/ci/variables/predefined_variables.html
disposable_env_only = pytest.mark.skipif(
    os.environ.get('CI_DISPOSABLE_ENVIRONMENT', '').lower() not in ('true', '1'),
    reason='Test must be run in a disposable environment',
)


@pytest.mark.unlicensed
def test_version(kx):
    assert re.fullmatch(r'(?:\d+\.){2}\d+.*', kx.__version__)


@pytest.mark.unlicensed
def test_dir(kx):
    assert isinstance(dir(kx), list)
    assert dir(kx) == sorted(dir(kx))


@pytest.mark.isolate
def test_qargs_q_flag():
    # PyKX used to fail on startup if the '-q' flag was manually provided
    os.environ['QARGS'] = '-q'
    import pykx as kx
    assert kx.q('2 + 2') == 4


@pytest.mark.isolate
def test_no_sql():
    os.environ['QARGS'] = '--no-sql'
    import pykx as kx
    with pytest.raises(kx.QError) as err:
        kx.q.sql('select 42')
    assert '.s.sp' in str(err)


@pytest.mark.isolate
@pytest.mark.skipif(not sys.platform.startswith('linux'), reason="qlog only supported on Linux")
def test_no_qlog():
    os.environ['QARGS'] = '--no-qlog'
    import pykx as kx
    with pytest.raises(kx.QError) as err:
        kx.q('.qlog')
    assert '.qlog' in str(err)


@pytest.mark.isolate
def test_qinit_startup():
    # PyKX would not initialise appropriately if QINIT was set to a file containing show statement
    os.environ['QINIT'] = 'tests/qinit.q'
    import pykx as kx
    assert kx.q('2 + 2') == 4


@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
def test_unlicensed_env():
    os.environ['PYKX_UNLICENSED'] = 'true'
    import pykx as kx
    assert not kx.licensed
    assert 1 == kx.toq(1).py()


@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
def test_qinit_qq_startup():
    # PyKX would not initialise appropriately if q.q exists in QHOME containing a show statement
    shutil.copy('tests/qinit.q', os.environ['QHOME']+'/q.q')
    import pykx as kx
    try_clean(os.environ['QHOME']+'/q.q')
    assert kx.q('2 + 2') == 4


@disposable_env_only
@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
def test_QHOME_symlinks():
    # This logic to get QHOME is copied from `pykx.config`, since we can't use `pykx.qhome` until
    # after PyKX has been imported, but that would ruin the test.
    try:
        QHOME = Path(os.environ.get('QHOME', Path().home()/'q')).resolve(strict=True)
    except FileNotFoundError:
        # If QHOME and its fallback weren't set/valid, then q/Python must be
        # running in the same directory as q.k (and presumably other stuff one
        # would expect to find in QHOME).
        QHOME = Path().resolve(strict=True)
    p = QHOME/'extra.q'
    p.write_text('a:1b\n')

    q_lib_dir_name = {
        'Darwin': 'm64',
        'Linux': 'l64',
        'Windows': 'w64',
    }[system()]
    (QHOME/q_lib_dir_name).mkdir(exist_ok=True)
    lib = Path('lib')/'4-1-libs' if os.getenv('PYKX_4_1_ENABLED') is not None else Path('lib')
    fake_q_lib_path = Path(site.getsitepackages()[0])/'pykx'/lib/q_lib_dir_name/'fake_q_lib.so'
    fake_q_lib_path.touch()
    # Convert first argument of `shutil.move` to `str` to work around Python bug bpo-32689
    shutil.move(str(fake_q_lib_path), QHOME/q_lib_dir_name)

    assert not fake_q_lib_path.exists()
    import pykx as kx
    assert kx.q.extra.a # Ensure the q file in the user QHOME directory is available via symlink.
    assert fake_q_lib_path.exists()
    assert fake_q_lib_path.is_symlink()


def try_clean(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


@disposable_env_only
@pytest.mark.isolate
def test_QHOME_symlinks_skip():
    os.environ['PYKX_IGNORE_QHOME'] = "1"
    # This logic to get QHOME is copied from `pykx.config`, since we can't use `pykx.qhome` until
    # after PyKX has been imported, but that would ruin the test.
    try:
        QHOME = Path(os.environ.get('QHOME', Path().home()/'q')).resolve(strict=True)
    except FileNotFoundError:
        # If QHOME and its fallback weren't set/valid, then q/Python must be
        # running in the same directory as q.k (and presumably other stuff one
        # would expect to find in QHOME).
        QHOME = Path().resolve(strict=True)
    p = QHOME/'skipped.q'
    p.write_text('a:1b\n')

    q_lib_dir_name = {
        'Darwin': 'm64',
        'Linux': 'l64',
        'Windows': 'w64',
    }[system()]
    (QHOME/q_lib_dir_name).mkdir(exist_ok=True)
    try_clean((QHOME/q_lib_dir_name/'fake_q_lib.so'))
    try_clean(Path(site.getsitepackages()[0])/'pykx'/'lib'/q_lib_dir_name/'fake_q_lib.so')
    fake_q_lib_path = Path(site.getsitepackages()[0])/'pykx'/'lib'/q_lib_dir_name/'fake_q_lib.so'
    fake_q_lib_path.touch()
    # Convert first argument of `shutil.move` to `str` to work around Python bug bpo-32689
    shutil.move(str(fake_q_lib_path), QHOME/q_lib_dir_name)
    try_clean(fake_q_lib_path)

    assert (QHOME/q_lib_dir_name).exists()
    assert (QHOME/'skipped.q').exists()
    assert not fake_q_lib_path.exists()
    import pykx as kx # noqa
    assert not fake_q_lib_path.exists()
    assert not (Path(site.getsitepackages()[0])/'pykx'/'skipped.q').exists()

    try_clean((QHOME/q_lib_dir_name/'fake_q_lib.so'))
    try_clean(fake_q_lib_path)


@pytest.mark.unlicensed
def test_top_level_attributes(kx):
    assert not set(dir(kx.exceptions)) - set(dir(kx))
    assert not set(dir(kx.wrappers)) - set(dir(kx))
    assert isinstance(kx.qhome, Path)
    assert isinstance(kx.qlic, Path)
    assert isinstance(kx.qargs, tuple)
    assert isinstance(kx.licensed, bool)
    assert isinstance(kx.q, kx.Q)
    assert isinstance(kx.q, kx.EmbeddedQ)
    assert issubclass(kx.EmbeddedQ, kx.Q)
    assert issubclass(kx.QConnection, kx.Q)


# TODO: Turn this text back on when the Q Lock timeout value is working again
# @pytest.mark.isolate
# def test_q_lock_error_timed():
#     import time
#
#     os.environ['PYKX_RELEASE_GIL'] = '1'
#     os.environ['PYKX_Q_LOCK'] = '3'
#
#     import pykx as kx
#
#     s = time.monotonic_ns()
#     with pytest.raises(kx.QError) as err:
#         kx.q('{[f] f peach til 20}', lambda x: kx.q(f'til {x}'))
#         assert 'Attempted to acquire lock on already locked call into q.' in str(err.value)
#     e = time.monotonic_ns()
#     run_time = (e - s) * 0.000000001 # convert time back to seconds
#     assert run_time > 3.0 and run_time < 4.0


@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
def test_q_lock_error_instant():
    os.environ['PYKX_RELEASE_GIL'] = '1'
    os.environ['PYKX_Q_LOCK'] = '0'

    import pykx as kx

    with pytest.raises(kx.QError) as err:
        kx.q('{[f] f peach til 20}', lambda x: kx.q(f'til {x}'))
        assert 'Attempted to acquire lock on already locked call into q.' in str(err.value)


@pytest.mark.isolate
def test_pykx_safe_reimport():
    import pykx as kx
    with kx.PyKXReimport():
        output = subprocess.run(
            (str(Path(sys.executable).as_posix()), '-c', 'import pykx; print(pykx.q("til 10"))'),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()
        assert output.split('\n')[-1] == "0 1 2 3 4 5 6 7 8 9"


@pytest.mark.isolate
def test_pykx_sigkill():
    returncode = subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c', 'import pykx as kx; import os; import signal; pid = os.getpid(); os.kill(pid, signal.SIGKILL)'), # noqa: E501
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).returncode
    assert returncode == -9


@pytest.mark.isolate
@pytest.mark.xfail(reason='Local testing shows appropriate behaviour')
def test_pykx_sigint():
    output = subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c', 'import pykx as kx; import os; import signal; pid = os.getpid(); os.kill(pid, signal.SIGINT)'), # noqa: E501
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.strip()
    assert output.split('\n')[-1] == 'KeyboardInterrupt'


@pytest.mark.isolate
def test_pykx_sigterm():
    returncode = subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c', 'import pykx as kx; import os; import signal; pid = os.getpid(); os.kill(pid, signal.SIGTERM)'), # noqa: E501
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).returncode
    assert returncode == -15


@pytest.mark.isolate
def test_pykx_star():
    output = subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c', 'from pykx import *; print(q("til 10"))'),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.strip()
    assert output.split('\n')[-1] == "0 1 2 3 4 5 6 7 8 9"


@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
@pytest.mark.skipif(
    (sys.version_info.major == 3) and (sys.version_info.minor == 8),
    reason="python3.8 subprocess behavior inconsistent with newest versions"
)
def test_pykx_stdout_stderr():
    output = subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c',
            'import pykx;pykx.q(\'\\l tests/qscripts/test_stdout_stderr.q\')'),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.strip()
    output = output.split('\n')
    output = [x for x in output if x[:13] == 'stdouterrtest']
    assert (lambda x: ([int(i.split(',')[1]) for i in x]))(output) == list(range(1, 23))


@pytest.mark.isolate
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
@pytest.mark.skipif(
    (sys.version_info.major == 3) and (sys.version_info.minor == 8),
    reason="python3.8 subprocess behavior inconsistent with newest versions"
)
def test_pykx_stdout_stderr_under_q():
    subprocess.run(
        (str(Path(sys.executable).as_posix()), '-c',
            'import pykx;pykx.install_into_QHOME(cloud_libraries=True)'),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = subprocess.run(
        ('q', 'tests/qscripts/test_stdout_stderr.q', '-q'),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.strip()
    output = output.split('\n')
    output = [x for x in output if x[:13] == 'stdouterrtest']
    assert (lambda x: ([int(i.split(',')[1]) for i in x]))(output) == list(range(1, 23))


@pytest.mark.isolate
def test_compressed_enum_segfault(kx):
    import tempfile
    temp_dir = tempfile.TemporaryDirectory()
    kx.q('{`base set hsym x}', temp_dir.name)
    kx.q('.z.zd:17 1 0')
    kx.q('n:10000')
    kx.q('trade:([] sym:`$string til n)')
    kx.q('.Q.dpft[base;;`sym;`trade] each 2020.01.01 + til 100')
    kx.q('system"l ",1_ string base')
    kx.q('select from trade')


def test_is_enabled(kx):
    assert kx.config.ignore_qhome is False


@pytest.mark.isolate
def test_PYKX_Q_LIB_LOCATION():
    import tempfile
    import importlib
    import shutil
    temp_dir = tempfile.TemporaryDirectory().name
    pykx_loc = os.path.dirname(importlib.util.find_spec("pykx").origin)
    shutil.copytree(os.path.join(pykx_loc, "lib"), temp_dir)
    os.environ['PYKX_Q_LIB_LOCATION'] = temp_dir
    file = os.path.join(temp_dir, "PYKX_Q_LIB_LOCATION.q")
    with open(file, 'w') as f:
        f.write('.pytest.a:42')
    import pykx as kx
    kx.q('\\l PYKX_Q_LIB_LOCATION.q')
    assert 42 == kx.q('.pytest.a').py()


@pytest.mark.unlicensed
@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subnormal updates not presently implemented on Windows'
)
def test_subnormals(kx):
    import numpy as np
    assert '5e-324' == str(np.finfo(np.float64).smallest_subnormal + 0.)


@pytest.mark.isolate
def test_import_cd():
    cd = os.getcwd()
    import pykx as kx # noqa: F401
    assert cd == os.getcwd()


@pytest.mark.xfail(reason='Allow to xfail if internet not available', strict=False)
def test_links():
    links = ['https://code.kx.com/q4m3/12_Workspace_Organization/#122-contexts',
             'https://numpy.org/neps/nep-0049.html',
             'https://code.kx.com/q/basics/internal/#-36-load-master-key',
             'https://code.kx.com/q/kb/file-compression/#compression-parameters',
             'https://code.kx.com/q/kb/file-compression/#compression-by-default',
             'https://code.kx.com/pykx/user-guide/configuration.html',
             'https://code.kx.com/q4m3/12_Workspace_Organization',
             'https://code.kx.com/q/basics/errors',
             'https://code.kx.com/q/kb/ssl',
             'https://code.kx.com/q/basics/ipc',
             'https://code.kx.com/q/kb/serialization',
             'https://github.com/kxsystems/pykx/issues',
             'https://code.kx.com/q4m3/9_Queries_q-sql/#912-functional-forms',
             'https://code.kx.com/q/basics/qsql/#result-and-side-effects',
             'https://code.kx.com/insights/core/sql.html',
             'https://github.com/KxSystems/kdb/blob/master/utils/csvutil.q',
             'https://code.kx.com/q/ref/upsert',
             'https://code.kx.com/q/ref/insert',
             'https://code.kx.com/q/basics/ipc/#handshake',
             'https://code.kx.com/pykx/user-guide/advanced/serialization.html',
             'https://code.kx.com/q/basics/syscmds/',
             'https://code.kx.com/q/basics/cmdline/',
             'https://code.kx.com/pykx/getting-started/installing.html',
             'https://code.kx.com/pykx/help/troubleshooting.html',
             'https://code.kx.com/q/ref/enumeration/',
             'https://code.kx.com/q/ref/enumerate/',
             'https://code.kx.com/q/ref/enum-extend/',
             'https://code.kx.com/q/basics/qsql/#result-and-side-effects.',
             'https://code.kx.com/q4m3/8_Tables/#84-primary-keys-and-keyed-tables',
             'https://code.kx.com/q4m3/6_Functions/',
             'https://code.kx.com/q/ref/#operators',
             'https://code.kx.com/q/ref/#iterators',
             'https://code.kx.com/q/ref/cast/']
    for url in links:
        req = requests.get(url)
        print(url, req.status_code)
        assert req.status_code == 200


def test_error_attrs(kx):
    attributes = ['_pyarrow.import_attempt_output', 'toq', 'Table', 'Compress', 'Encrypt',
                  'DB', 'license.install', 'SplayedTable', 'PartitionedTable',
                  'Dictionary', 'Foreign', 'Column', 'Column.fby', 'QueryPhrase']
    for i in attributes:
        try:
            operator.attrgetter(i)(kx)
        except BaseException as err:
            raise AssertionError(f"Exception {err} raised when retrieving atrribute {i}")

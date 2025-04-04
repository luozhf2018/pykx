import asyncio
from contextlib import contextmanager
from datetime import date
from io import StringIO
import os
from platform import system, uname
import signal
import subprocess
import sys
from textwrap import dedent
import time
from uuid import uuid4


# Do not import pykx here - use the `kx` fixture instead!
import pytest


@contextmanager
def replace_stdin(new_stdin):
    orig_stdin = sys.stdin
    sys.stdin = new_stdin
    yield
    sys.stdin = orig_stdin


test_arr = []


def _generic_ipc_test(conn):
    atom_test = conn('1+1')
    assert atom_test.py() == 2
    tab_test = conn('([]10?1f;10?1f)')
    assert tab_test.t == 98
    func_eval = conn('{x+til y}', 1, 2)
    assert func_eval.py() == [1, 2]
    async_eval = conn('{a::{x+y}[x;y]}', 10, 10, wait=False)
    assert async_eval.t == 101
    assert conn('a').py() == 20
    conn('b:5', wait=False)
    assert conn('b').py() == 5
    assert isinstance(conn.fileno(), int)
    assert conn('{[a;b;c;d;e;f;g;h]a+b*c-d-f+g*h}', 1, 2, 3, 4, 5, 6, 7, 8).py() == 123
    guid = uuid4()
    assert conn('{x}', guid).py() == guid
    with pytest.raises(TypeError):
        conn('', 1, 2, 3, 4, 5, 6, 7, 8, 9)
    conn.close()
    with pytest.raises(RuntimeError):
        conn('1+1')


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_eventloop_gather_order(kx, q_port, event_loop):
    global test_arr
    test_arr = []

    async def _sub_test(q_ipc):
        global test_arr
        test_arr.append((await q_ipc('{t:.z.p;while[.z.p<t+00:00:01]; til 10}[::]')).py())
        test_arr.append((await q_ipc('{t:.z.p;while[.z.p<t+00:00:01]; til 20}[::]')).py())

    async with kx.AsyncQConnection(port=q_port, event_loop=event_loop) as q:
        coros = [_sub_test(q) for _ in range(2)]
        await asyncio.gather(*coros)
    with kx.QConnection(port=q_port) as q:
        assert test_arr == [q('til 10').py(), q('til 10').py(), q('til 20').py(), q('til 20').py()]


@pytest.mark.unlicensed
def test_max_error_length(kx, q_port):
    with kx.QConnection('localhost', q_port) as q:
        with pytest.raises(kx.QError) as err:
            q('\'1000?"abcd"')
            assert len(str(err.value)) == 256
        os.environ['PYKX_MAX_ERROR_LENGTH'] = "10"
        with pytest.raises(kx.QError) as err:
            q('\'1000?"abcd"')
            assert len(str(err.value)) == 10
        os.environ['PYKX_MAX_ERROR_LENGTH'] = "256" # ensure it is reset to default for later tests


@pytest.mark.unlicensed
def test_ipc_messaging_tcp(kx, q_port):
    with kx.QConnection('localhost', q_port) as q:
        _generic_ipc_test(q)


@pytest.mark.unlicensed
@pytest.mark.parametrize('q_init', [[b'.z.pw:{(x~`username)&y~"password"}\n']])
def test_ipc_messaging_tcp_auth(kx, q_port):
    with kx.QConnection('localhost', q_port, username='username', password='password') as q:
        _generic_ipc_test(q)


@pytest.mark.unlicensed
def test_ipc_messaging_tcp_compression_edge_case(kx, q_port):
    with kx.QConnection('localhost', q_port) as q:
        q._create_result(bytearray(b'\x01\x02\x01\x00c\x00\x00\x00\x80\x08\x00\x00\x00\n\x00r\x08\x00\x00ab\x00cdefghij\x00klmnopqr\x00stuvwxyz\x00abcdefgh@ijklmn\x1f\xfflE\x03\xffj\x07\xffhij\x07\xffhE\x03\xfff\x0f\xffdef\x0f\xffd\x11\x03\xffbcd\x032'))  # noqa


def unix_test(f):
    def wrapper(kx, q_port):
        if system() == 'Windows':
            with pytest.raises(TypeError):
                f(kx, q_port)
        else:
            f(kx, q_port)
    return wrapper


@pytest.mark.unlicensed
@unix_test
def test_ipc_messaging_unix(kx, q_port):
    with kx.QConnection(port=q_port, unix=True) as q:
        _generic_ipc_test(q)


@pytest.mark.unlicensed
@pytest.mark.parametrize('q_init', [[b'.z.pw:{(x~`username)&y~"password"}\n']])
@unix_test
def test_ipc_messaging_unix_auth(kx, q_port):
    with kx.QConnection(port=q_port, username='username', password='password', unix=True) as q:
        _generic_ipc_test(q)


def test_memory_domain(q, kx, q_port):
    memory_domain = q('-120!')
    assert 0 == memory_domain(q('`asdf'))
    assert 0 == memory_domain(kx.K('asdf'))
    with kx.QConnection(port=q_port) as q:
        assert 0 == memory_domain(q('`asdf'))


@pytest.mark.unlicensed
def test_port_provided(kx):
    with pytest.raises(TypeError):
        kx.QConnection()
    with pytest.raises(TypeError):
        kx.QConnection(host='localhost')
    with pytest.raises(TypeError):
        kx.QConnection(unix=True)


@pytest.mark.unlicensed
def test_timeout(kx, q_port):
    with kx.SyncQConnection('localhost', q_port, timeout=2.0) as q:
        with pytest.raises(kx.QError):
            q('{t:.z.p;while[.z.p<t+00:00:05]; x} til 10')
        assert [0, 1, 2, 3, 4] == q('til 5').py()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_repr(kx, q_port):
    assert repr(await kx.AsyncQConnection(port=q_port)) == f'pykx.AsyncQConnection(port={q_port!r})'


@pytest.mark.large
@pytest.mark.unlicensed
def test_random_large_bytevector(kx, q_port):
    with kx.QConnection(port=q_port) as q:
        a = q('8178374?0x00')
        assert q('{0N!x}', a).py() == a.py()


@pytest.mark.unlicensed
def test_repr(kx, q_port):
    assert repr(kx.QConnection(port=q_port)) == f'pykx.QConnection(port={q_port!r})'
    assert repr(kx.SyncQConnection(port=q_port)) == f'pykx.QConnection(port={q_port!r})'


@pytest.mark.unlicensed
def test_no_ctx(kx, q_port):
    with kx.QConnection(port=q_port, no_ctx=True) as q:
        til_5 = [0, 1, 2, 3, 4]
        mavg = [0, 0.5, 1.5, 2.5, 3.5]
        assert til_5 == q.til(5).py()
        assert mavg == q.mavg(2, til_5).py()
        with pytest.raises(kx.PyKXException):
            q.a(10)


@pytest.mark.unlicensed
def test_no_ctx_not_used(kx, q_port):
    with kx.QConnection(port=q_port) as q:
        til_5 = [0, 1, 2, 3, 4]
        mavg = [0, 0.5, 1.5, 2.5, 3.5]
        assert til_5 == q('til 5').py()
        assert til_5 == q.til(5).py()
        assert mavg == q('mavg[2; til 5]').py()
        assert mavg == q.mavg(2, til_5).py()


@pytest.mark.unlicensed
def test_pykx_ctx_remote(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        q('.pykx.test_tab:([]10?1f;10?1f)')
        assert isinstance(q.meta('.pykx.test_tab'), kx.KeyedTable)


@pytest.mark.unlicensed
def test_no_pykx_namespace(kx, q_port):
    with kx.QConnection(port=q_port) as q:
        assert 'pykx' not in q('key `').py()


def test_no_pyfunc_over_ipc(kx, q_port):
    q = kx.QConnection(port=q_port)
    assert sum(q('{z x+y}', 3, 5, q('til')).py()) == 28
    with pytest.raises(ValueError):
        q('{z x+y}', 3, 5, lambda x: range(x))


def test_no_wrap_over_ipc(kx, q_port):
    q = kx.QConnection(port=q_port)
    with pytest.raises(ValueError):
        q('{x}', kx.q('{x}', round))


def test_symbolic_function(kx, q_port):
    kx.q('.my.func:{x+1}')
    with kx.SyncQConnection(port=q_port) as conn:
        assert conn(kx.q.my.func, 1) == kx.q('2')


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_deferred_calls(kx, q_port):
    async with kx.AsyncQConnection(port=q_port) as q:
        await q('f: {h::.z.w; -30!(::); show h; show type h; -30!(h; 0b; `hello`world)}')

        a = q('til 5')
        b = q('f[]', reuse=False)
        c = q('f[]', reuse=False)
        d = q('til 10')
        e = q('til 20')
        f = q('f[]', reuse=False)

        assert (await a).py() == list(range(5))
        assert (await b).py() == ['hello', 'world']
        assert (await e).py() == list(range(20))
        assert (await f).py() == ['hello', 'world']
        assert (await c).py() == ['hello', 'world']
        assert (await d).py() == list(range(10))


@pytest.mark.unlicensed
def test_async_with_q_features(kx, q_port):
    q = kx.QConnection(port=q_port, wait=False)
    assert q.Q.n.py() == b'0123456789'
    with StringIO('t:([k1:1 2 3; k2:`x`y`z] m:2022.01.01 2022.02.02 2022.03.03)\n\\\\') as stdin:
        with replace_stdin(stdin):
            q.console()
    t = {
        (1, 'x'): {'m': date(2022, 1, 1)},
        (2, 'y'): {'m': date(2022, 2, 2)},
        (3, 'z'): {'m': date(2022, 3, 3)},
    }
    assert q['t'].py() == t
    q['a'] = 'z'
    assert q['a'].py() == 'z'
    assert q.qsql.select('t').py() == t
    assert q.qsql.exec('t', where=['m>2022.02.02']).py() == \
        {'k1': 3, 'k2': 'z', 'm': date(2022, 3, 3)}
    q.qsql.update('t', inplace='sure', columns={'j': '"j"$m*2'}, where=['m>2022.02.01', 'k1<3'])
    assert q('t . ((2;`y);`j)', wait=True).py() == 16136
    assert q.qsql.delete('t', 'm').values().keys().py() == ['j']


@pytest.mark.unlicensed
def test_dir(kx):
    assert isinstance(dir(kx.ipc), list)
    assert sorted(dir(kx.ipc)) == dir(kx.ipc)


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_q_connection(kx, q_port):
    with kx.QConnection(port=q_port) as q:
        til_ten = q('til 10').py()
    q = await kx.AsyncQConnection(port=q_port)
    assert (await q('til 10')).py() == til_ten

    await q.close()
    async with kx.AsyncQConnection(port=q_port) as q:
        assert (await q('til 10')).py() == til_ten
        assert isinstance(q.fileno(), int)


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_tls_and_unix_error(kx, q_port):
    if system() == 'Windows':
        pass
        # with pytest.raises(TypeError):
        #     await kx.AsyncQConnection(port=q_port, tls=True, unix=True)
        # with pytest.raises(TypeError):
        #     kx.QConnection(port=q_port, tls=True, unix=True)
    else:
        with pytest.raises(kx.PyKXException):
            await kx.AsyncQConnection(port=q_port, tls=True, unix=True)
        with pytest.raises(kx.PyKXException):
            kx.QConnection(port=q_port, tls=True, unix=True)


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_q_connection_clears_calls_on_close(kx, q_port):
    async with kx.AsyncQConnection(port=q_port) as q:
        q('til 10')
        q('til 5')
        assert len(q._call_stack) == 2
        await q.close()
        assert len(q._call_stack) == 0


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
@pytest.mark.skipif(
    os.getenv('PYKX_THREADING') is not None,
    reason='Not supported with PYKX_THREADING'
)
def test_py_file_execution(kx):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()
    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15005'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)
    with kx.SyncQConnection(port=15005) as q:
        with pytest.raises(kx.QError) as err:
            q.file_execute('./tests/qscripts/file.l')
        assert "Provided file type 'l' unsupported" == str(err.value)
        with pytest.raises(kx.QError) as err:
            q.file_execute('./tests/qscripts/pyfile.py', return_all=True)
        assert "PyKX must be loaded on remote server" == str(err.value)
        q('\l pykx.q')
        q.file_execute('./tests/qscripts/pyfile.py')
        assert q('.pykx.get[`pyfunc;<][2;3]') == 6
    proc.kill()
    time.sleep(2)


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
def test_sync_file_execution(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        q.file_execute('./tests/qscripts/sync_file_exec.q')
        assert q('.test.sync').py()


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
@pytest.mark.asyncio
async def test_async_file_execution(kx, q_port):
    async with kx.AsyncQConnection(port=q_port) as q:
        q.file_execute('./tests/qscripts/async_file_exec.q')
        assert (await q('.test.async')).py()


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
def test_sync_file_execution_fail(kx, q_port):
    with pytest.raises(kx.QError):
        with kx.SyncQConnection(port=q_port) as q:
            q.file_execute('./tests/qscripts/sync_file_fail.q', return_all=True)


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
def test_file_execution_newline(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        ret = q.file_execute('./tests/qscripts/empty_line.q', return_all=True)
    assert ret[-1] == 101


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_async_q_connection(kx, q_port):
    with kx.QConnection(port=q_port) as q:
        til_ten = q('til 10').py()
        til_twenty = q('til 20').py()

    async with kx.AsyncQConnection(port=q_port) as q:
        calls = [q('til 10'), q('til 5', wait=False), q('til 20')]
        assert til_ten == (await calls[0]).py()
        assert isinstance(await calls[1], kx.Identity)
        assert til_twenty == (await calls[2]).py()


@pytest.mark.unlicensed
def test_secure_q_con_callable(kx, q_port):
    with kx.SecureQConnection(port=q_port) as q:
        assert list(range(10)) == q('til 10').py()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_uninitialized_connection(kx, q_port):
    with pytest.raises(kx.UninitializedConnection):
        q = kx.AsyncQConnection(port=q_port)
        await q('til 10')
    with pytest.raises(kx.UninitializedConnection):
        q = kx.AsyncQConnection(port=q_port)
        await q.close()
    with pytest.raises(kx.UninitializedConnection):
        q = kx.AsyncQConnection(port=q_port)
        q.fileno()


@pytest.mark.unlicensed
@pytest.mark.skipif(
    system() == 'Windows',
    reason='SSL test updates not presently implemented on Windows'
)
def test_ssl_info(kx):
    if (system() == 'Linux') & (uname()[4] == 'x86_64'):
        assert isinstance(kx.ssl_info(), kx.Dictionary)


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_raw_poll_send_recv_all(kx, q_port, event_loop):
    async with kx.RawQConnection(port=q_port, event_loop=event_loop) as q:
        calls = []
        for i in range(10):
            calls.append(q(f'til {10 + i}'))
            assert not calls[i].done()

        assert len(q._send_stack) == 10
        q.poll_send(0)
        time.sleep(1)
        assert len(q._send_stack) == 0

        assert len(q._call_stack) == 10
        q.poll_recv(0)
        time.sleep(1)
        assert len(q._call_stack) == 0

        for i in range(10):
            assert (await calls[i]).py() == list(range(10 + i))
            assert calls[i].done()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_raw_poll_send_recv_one(kx, q_port, event_loop):
    async with kx.RawQConnection(port=q_port, event_loop=event_loop) as q:
        calls = []
        for i in range(10):
            calls.append(q(f'til {10 + i}'))
            assert not calls[i].done()

        assert len(q._send_stack) == 10
        assert len(q._call_stack) == 10
        for _ in range(15):
            q.poll_send()
            time.sleep(0.2)
            q.poll_recv()
            time.sleep(0.2)

        assert len(q._send_stack) == 0
        assert len(q._call_stack) == 0
        for i in range(10):
            assert (await calls[i]).py() == list(range(10 + i))
            assert calls[i].done()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_raw_poll_send_recv_n(kx, q_port, event_loop):
    async with kx.RawQConnection(port=q_port, event_loop=event_loop) as q:
        calls = []
        for i in range(10):
            calls.append(q(f'til {10 + i}'))
            assert not calls[i].done()

        assert len(q._send_stack) == 10
        assert len(q._call_stack) == 10
        for _ in range(7):
            q.poll_send(2)
            time.sleep(1)
            q.poll_recv(2)
            time.sleep(0.5)

        assert len(q._send_stack) == 0
        assert len(q._call_stack) == 0
        for i in range(10):
            assert (await calls[i]).py() == list(range(10 + i))
            assert calls[i].done()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_raw_await(kx, q_port, event_loop):
    async with kx.RawQConnection(port=q_port, event_loop=event_loop) as q:
        calls = []
        for i in range(10):
            calls.append(q(f'til {10 + i}'))
            assert not calls[i].done()

        for i in range(9, -1, -1): # Reverse of range(10) to ensure out of order await works
            assert (await calls[i]).py() == list(range(10 + i))


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_raw_complex(kx, q_port, event_loop):
    async with kx.RawQConnection(port=q_port, event_loop=event_loop) as q:
        await q('py_server: neg .z.w')
        await q('py_server ""; '
                '{[x] py_server[x]; py_server[til x]; py_server[x * x]} each 5 + til 5;',
                wait=False
        )

        results = []
        for _ in range(25):
            results.append(q.poll_recv())
        results = [x for x in results if x is not None]

        for i in range(5, 10):
            assert results.pop(0).py() == i
            assert results.pop(0).py() == list(range(i))
            assert results.pop(0).py() == i * i


@pytest.mark.isolate
def test_tls():
    if os.getenv('CI') is not None and sys.platform == 'linux':
        from .conftest import random_free_port
        with open('makeCerts.sh', 'w') as f:
            f.write(dedent("""#!/bin/bash -x

                ROOT=$(readlink -f $(dirname $BASH_SOURCE))
                mkdir -p $ROOT/certs && cd $ROOT/certs

                # Create CA certificate
                openssl genrsa 2048 > ca-key.pem
                openssl req -new -x509 -nodes -days 3600 \\
                    -key ca-key.pem -out ca.pem -extensions usr_cert \\
                    -subj '/C=US/ST=New York/L=Brooklyn/O=Example Brooklyn Company/CN=examplebrooklyn.com'

                # Create server certificate, remove passphrase, and sign it
                # server-crt.pem = public key, server-key.pem = private key
                openssl req -newkey rsa:2048 -days 3600 -nodes \\
                    -keyout server-key.pem -out server-req.pem -extensions usr_cert \\
                    -subj '/C=US/ST=New York/L=Brooklyn/O=Example Brooklyn Company/CN=myname.com'
                openssl rsa -in server-key.pem -out server-key.pem
                openssl x509 -req -in server-req.pem -days 3600 -CA ca.pem -CAkey ca-key.pem \\
                    -set_serial 01 -out server-crt.pem -extensions usr_cert

                # Create client certificate, remove passphrase, and sign it
                # client-crt.pem = public key, client-key.pem = private key
                openssl req -newkey rsa:2048 -days 3600  -nodes \\
                    -keyout client-key.pem -out client-req.pem -extensions usr_cert \\
                    -subj '/C=US/ST=New York/L=Brooklyn/O=Example Brooklyn Company/CN=myname.com'
                openssl rsa -in client-key.pem -out client-key.pem
                openssl x509 -req -in client-req.pem -days 3600 -CA ca.pem -CAkey ca-key.pem \\
                    -set_serial 01 -out client-crt.pem -extensions usr_cert""")) # noqa
        os.system('chmod +x ./makeCerts.sh')
        os.system('./makeCerts.sh')
        original_QHOME = os.environ['QHOME']
        proc = None
        try:
            q_init = [b'']
            port = random_free_port()
            proc = subprocess.Popen(
                (lambda x: x.split() if system() != 'Windows' else x)(f'q -E 2 -p {port}'),
                stdin=subprocess.PIPE,
                stdout=subprocess.sys.stdout,
                stderr=subprocess.sys.stderr,
                start_new_session=True,
                env={
                    **os.environ,
                    'QHOME': original_QHOME,
                    'KX_SSL_CERT_FILE': './certs/server-crt.pem',
                    'KX_SSL_KEY_FILE': './certs/server-key.pem',
                    'KX_SSL_NO_VERIFY': '1'
                },
            )
            q_init.append((f'system"kill -USR1 {os.getpid()}"').encode())
            proc.stdin.write(b'\n'.join((*q_init, b'')))
            proc.stdin.flush()
            signal.sigwait([signal.SIGUSR1]) # Wait until all initial queries have been run

            os.environ['KX_SSL_CERT_FILE'] = './certs/server-crt.pem'
            os.environ['KX_SSL_CA_CERT_FILE'] = './certs/ca.pem'
            os.environ['KX_SSL_VERIFY_SERVER'] = 'NO'
            import pykx as kx
            with kx.QConnection(port=port, tls=True) as q:
                assert q('til 10').py() == list(range(10))
            with kx.SyncQConnection(port=port, tls=True) as q:
                assert q('til 10').py() == list(range(10))
            with kx.SecureQConnection(port=port, tls=True) as q:
                assert q('til 10').py() == list(range(10))
            with kx.QConnection(port=port, tls=True) as q:
                q('func:{x}')
                assert q('func', 1).py() == 1
                assert q(b'func', 1).py() == 1
                assert q(kx.CharVector('func'), 1).py() == 1
                assert q(kx.SymbolAtom('func'), 1).py() == 1
                assert q(q('{x}'), 1).py() == 1
        finally:
            if proc is not None:
                proc.stdin.close()
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.terminate()
                proc.wait()
        # This will fail before actually trying to connect
        with pytest.raises(kx.PyKXException):
            with kx.AsyncQConnection(port=5000, tls=True) as q:
                assert q('til 10').py() == list(range(10))
        # This will fail before actually trying to connect
        with pytest.raises(kx.PyKXException):
            with kx.RawQConnection(port=5000, tls=True) as q:
                assert q('til 10').py() == list(range(10))


@pytest.mark.xfail(reason='ToDo: Resolve KXI-30608', strict=False)
@pytest.mark.isolate
@pytest.mark.unlicensed
def test_server(kx):
    if os.getenv('CI') is not None:
        from .conftest import random_free_port
        original_QHOME = os.environ['QHOME']
        proc = None
        try:
            q_init = [b'']
            port = random_free_port()
            with kx.PyKXReimport():
                env_vars = {
                    **os.environ,
                    'QHOME': original_QHOME
                }
                env_vars.pop('PYKX_Q_LOADED_MARKER', None)
                env_vars.pop('QARGS', None)
                proc = subprocess.Popen(
                    (lambda x: x.split() if system() != 'Windows' else x)
                    (f'python ./docs/examples/server/server.py {port}'),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.sys.stdout,
                    stderr=subprocess.sys.stderr,
                    start_new_session=True,
                    env=env_vars,
                )
                q_init.append((f'system"kill -USR1 {os.getpid()}"').encode())
                proc.stdin.write(b'\n'.join((*q_init, b'')))
                proc.stdin.flush()
            time.sleep(10)
            import pykx as kx
            with kx.QConnection(port=port, no_ctx=True) as q:
                assert q('til 10').py() == list(range(10))
            with kx.QConnection(port=port, no_ctx=True, wait=False) as q:
                assert not q('a:til 10').py()
            with kx.QConnection(port=port, no_ctx=True, wait=False) as q:
                assert not q('1+`').py()
            with kx.QConnection(port=port, no_ctx=True) as q:
                assert q('a').py() == list(range(10))
            with kx.QConnection(port=port, no_ctx=True) as q:
                with pytest.raises(kx.QError):
                    q('1+`')
            with kx.QConnection(port=port, no_ctx=True) as q:
                with pytest.raises(kx.QError):
                    q('.pykx.i.repr')
            with kx.QConnection(port=port, no_ctx=True) as q:
                with pytest.raises(kx.QError) as err:
                    q('.pykx.getattr')
                e = str(err.value)
                assert "Result of query with return type '<class 'pykx.wrappers.Foreign" in e
            with kx.QConnection(port=port, no_ctx=True) as q:
                with pytest.raises(kx.QError) as err:
                    q('.pykx.pyeval')
                e = str(err.value)
                assert "Result of query with return type '<class 'pykx.wrappers.Projection" in e
            with kx.QConnection(port=port, no_ctx=True) as q:
                with pytest.raises(kx.QError) as err:
                    q('.pykx.preinit')
                e = str(err.value)
                assert "Result of query with return type '<class 'pykx.wrappers.Lambda" in e
        finally:
            if proc is not None:
                proc.stdin.close()
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.terminate()
                proc.wait()


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_helpful_error_for_closed_conn(kx, q_port):
    with pytest.raises(RuntimeError):
        async with kx.AsyncQConnection(port=q_port) as q:
            await q('hclose .z.w; til 10')


@pytest.mark.unlicensed
def test_sync_helpful_error_for_closed_conn(kx, q_port):
    with pytest.raises(RuntimeError):
        with kx.SyncQConnection(port=q_port) as q:
            q('hclose .z.w; til 10')


def check_enough_memory(GiB):
    import psutil
    minimum_memory = GiB
    memory_size = psutil.virtual_memory().available >> 30
    return memory_size >= minimum_memory


@pytest.mark.large
@pytest.mark.unlicensed
@pytest.mark.timeout(60)
@pytest.mark.skipif(not check_enough_memory(25), reason='Not enough memory')
def test_large_IPC(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        size = 4294967296 # Exceed 32 bit unsigned
        res = q('{x#0x0}', size)
        assert size == len(res)


@pytest.mark.unlicensed
def test_func_parameter(kx, q_port):
    # The below tests are formatted as follows
    # to allow operation both in licensed and
    # unlicensed mode, the initial call retrieves
    # the function and the assertion passes the
    # tested functions to the server as the query arg
    with kx.SyncQConnection(port=q_port) as q:
        fn = q('{sum}', None)
        assert q(fn, [1, 2, 3]).py() == 6

        fn = q('{floor}', None)
        assert q(fn, 5.2).py() == 5

        fn = q('{mins}', None)
        assert q(fn, [1, 2, 3]).py() == [1, 1, 1]

        fn = q('{cut}', None)
        assert q(fn, 2, [1, 2, 3]).py() == [[1, 2], [3]]

        fn = q('{min x}')
        assert q(fn, [1, 2, 3]).py() == 1

    if kx.licensed:
        with kx.SecureQConnection(port=q_port) as q:
            fn = q('{sum}', None)
            assert q(fn, [1, 2, 3]).py() == 6

            fn = q('{floor}', None)
            assert q(fn, 5.2).py() == 5

            fn = q('{mins}', None)
            assert q(fn, [1, 2, 3]).py() == [1, 1, 1]

            fn = q('{cut}', None)
            assert q(fn, 2, [1, 2, 3]).py() == [[1, 2], [3]]

            fn = q('{min x}')
            assert q(fn, [1, 2, 3]).py() == 1


@pytest.mark.unlicensed
def test_func_errors(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        with pytest.raises(ValueError) as err:
            q(sum, [1, 2, 3])
        assert 'builtin_function_or_method' in str(err)

    with kx.SecureQConnection(port=q_port) as q:
        with pytest.raises(ValueError) as err:
            q(sum, [1, 2, 3])
        assert 'builtin_function_or_method' in str(err)


@pytest.mark.unlicensed
def test_debug_kwarg(kx, q_port):
    with kx.SyncQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert q('til 10', debug=True).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('til "asd"', debug=True)
        assert 'type' in str(e)

        assert q('{[x] til x}', 10, debug=True).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('{til x}', b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{til x}' == q('.pykx_test.cache').py()[1][1][-1]

        assert q('{[x; y] .[mavg; (x; til y)]}', 3, 10, debug=True).py() ==\
            [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == q('.pykx_test.cache').py()[1][1][-1]
        q('.Q.sbt:.pykx_test.cache_sbt')

    with kx.SecureQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert q('til 10', debug=True).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('til "asd"')
        assert 'type' in str(e)

        assert q('{[x] til x}', 10, debug=True).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('{til x}', b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{til x}' == q('.pykx_test.cache').py()[1][1][-1]

        assert q('{[x; y] .[mavg; (x; til y)]}', 3, 10, debug=True).py() ==\
            [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == q('.pykx_test.cache').py()[1][1][-1]

        q('.Q.sbt:.pykx_test.cache_sbt')


@pytest.mark.isolate
def test_debug_kwarg_global(q_port):
    os.environ['PYKX_QDEBUG'] = 'True'
    import pykx as kx
    with kx.SyncQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert q('=', b'z', b'z').py()
        assert q('til 10').py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('til "asd"')
        assert 'type' in str(e)

        assert q('{[x] til x}', 10).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('{til x}', b'asd')
        assert 'type' in str(e)
        assert b'{til x}' == q('.pykx_test.cache')[1][1][-1].py()

        assert q('{[x; y] .[mavg; (x; til y)]}', 3, 10).py() ==\
            [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd')
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == q('.pykx_test.cache')[1][1][-1].py()
        q('.Q.sbt:.pykx_test.cache_sbt')

    with kx.SecureQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert q('til 10').py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('til "asd"')
        assert 'type' in str(e)

        assert q('{[x] til x}', 10, debug=True).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            q('{til x}', b'asd')
        assert 'type' in str(e)
        assert b'{til x}' == q('.pykx_test.cache')[1][1][-1].py()

        assert q('{[x; y] .[mavg; (x; til y)]}', 3, 10).py() ==\
            [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd')
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == q('.pykx_test.cache')[1][1][-1].py()
        q('.Q.sbt:.pykx_test.cache_sbt')


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_debug_kwarg_async(kx, q_port):
    async with kx.AsyncQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert (await q('til 10', debug=True)).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            await q('til "asd"')
        assert 'type' in str(e)

        assert (await q('{[x] til x}', 10, debug=True)).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            await q('{til x}', b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{til x}' == (await q('.pykx_test.cache')).py()[1][1][-1]

        assert (await q('{[x; y] .[mavg; (x; til y)]}', 3, 10, debug=True)).py()\
            == [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            await q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd', debug=True)
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == (await q('.pykx_test.cache')).py()[1][1][-1]

        q('.Q.sbt:.pykx_test.cache_sbt')


@pytest.mark.isolate
@pytest.mark.asyncio
async def test_debug_kwarg_async_global(q_port):
    import os
    os.environ['PYKX_QDEBUG'] = 'True'
    import pykx as kx
    async with kx.AsyncQConnection(port=q_port) as q:
        q('.pykx_test.cache_sbt:.Q.sbt')
        q('.Q.sbt:{.pykx_test.cache:y;x y}[.Q.sbt]')
        assert (await q('til 10')).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            await q('til "asd"')
        assert 'type' in str(e)

        assert (await q('{[x] til x}', 10)).py() == list(range(10))
        with pytest.raises(kx.QError) as e:
            await q('{til x}', b'asd')
        assert 'type' in str(e)
        assert b'{til x}' == (await q('.pykx_test.cache'))[1][1][-1].py()

        assert (await q('{[x; y] .[mavg; (x; til y)]}', 3, 10, debug=True)).py()\
            == [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        with pytest.raises(kx.QError) as e:
            await q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd')
        assert 'type' in str(e)
        assert b'{[x; y] .[mavg; (x; til y)]}' == (await q('.pykx_test.cache'))[1][1][-1].py()
        q('.Q.sbt:.pykx_test.cache_sbt')


@pytest.mark.embedded
async def test_debug_kwarg_embedded(kx, q):
    assert q('til 10', debug=True).py() == list(range(10))
    with pytest.raises(kx.QError) as e:
        q('til "asd"')
        assert '[1]' in str(e)
    assert q('{[x] til x}', 10, debug=True).py() == list(range(10))
    with pytest.raises(kx.QError) as e:
        q('{[x] til x}', b'asd')
        assert '[1]' in str(e)
    assert q('{[x; y] .[mavg; (x; til y)]}', 3, 10, debug=True).py() ==\
        [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    with pytest.raises(kx.QError) as e:
        q('{[x; y] .[mavg; (x; til y)]}', 3, b'asd')
        assert '[1]' in str(e)


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Temporary file testing flaky, requires rework'
)
@pytest.mark.unlicensed
def test_context_loadfile(kx):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()
    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15023'],
        )
    time.sleep(2)
    conn = kx.SyncQConnection(port=15023)
    try:
        assert isinstance(conn.csvutil, kx.ctx.QContext)
    except BaseException:
        proc.kill()
        assert 1==0 # Force failure in the case csvutil not available as a ctx
    proc.kill()


@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
@pytest.mark.unlicensed
def test_SyncQConnection_reconnect(kx, capsys):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()
    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15001'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)

    conn = kx.QConnection(port=15001, reconnection_attempts=3)

    assert conn('til 20').py() == list(range(20))
    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' in captured.err
    assert 'trying again in 1.0 seconds' in captured.err

    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15001'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)
    assert conn('til 10').py() == list(range(10))

    conn = kx.QConnection(port=15001, reconnection_attempts=3, reconnection_delay=1.0)
    assert conn('til 10').py() == list(range(10))

    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' not in captured.err
    assert 'trying again in 1.0 seconds' in captured.err
    assert 'trying again in 2.0 seconds' in captured.err

    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15001'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)
    conn = kx.QConnection(port=15001,
                          reconnection_attempts=3,
                          reconnection_delay=1.0,
                          reconnection_function=lambda x: x)
    assert conn('til 10').py() == list(range(10))

    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' not in captured.err
    assert 'trying again in 1.0 seconds' in captured.err
    assert 'trying again in 2.0 seconds' not in captured.err

    proc.kill()
    time.sleep(2)


@pytest.mark.unlicensed
@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
@pytest.mark.xfail(reason='Flaky on several platforms')
def test_SecureQConnection_reconnect(kx, capsys):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()
    proc = subprocess.Popen(
        [q_exe_path, '-p', '15002'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    time.sleep(2)

    conn = kx.SecureQConnection(port=15002, reconnection_attempts=3)

    assert conn('til 20').py() == list(range(20))
    proc.kill()
    time.sleep(2)
    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' in captured.err
    assert 'trying again in 1.0 seconds' in captured.err

    proc = subprocess.Popen(
        [q_exe_path, '-p', '15002'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    time.sleep(2)
    assert conn('til 10').py() == list(range(10))

    conn = kx.SecureQConnection(port=15002, reconnection_attempts=3, reconnection_delay=1.0)
    assert conn('til 10').py() == list(range(10))

    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' not in captured.err
    assert 'trying again in 1.0 seconds' in captured.err
    assert 'trying again in 2.0 seconds' in captured.err

    proc = subprocess.Popen(
        [q_exe_path, '-p', '15002'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    time.sleep(2)
    conn = kx.SecureQConnection(port=15002,
                                reconnection_attempts=3,
                                reconnection_delay=1.0,
                                reconnection_function=lambda x: x)
    assert conn('til 10').py() == list(range(10))

    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' not in captured.err
    assert 'trying again in 1.0 seconds' in captured.err
    assert 'trying again in 2.0 seconds' not in captured.err

    proc.kill()
    time.sleep(2)


@pytest.mark.asyncio
@pytest.mark.unlicensed
@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
async def test_AsyncQConnection_reconnect_with_event_loop(kx, event_loop, capsys):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()

    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15004'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)

    conn = await kx.AsyncQConnection(
        port=15004,
        reconnection_attempts=3,
        event_loop=event_loop
    )

    assert (await conn('til 20')).py() == list(range(20))
    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        await conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' in captured.err
    assert 'trying again in 1.0 seconds' in captured.err

    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15004'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)
    assert (await conn('10?`a`b`c`d')).py() is None
    assert (await conn('til 10')).py() == list(range(10))
    fut = conn('{t:.z.p;while[.z.p<t+x]; 10?`a`b`c`d} 00:00:05')
    fut2 = conn('{t:.z.p;while[.z.p<t+x]; 10?`a`b`c`d} 00:00:05')
    proc.kill()
    time.sleep(2)
    with pytest.raises(BaseException):
        await fut
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' in captured.err
    assert 'trying again in 1.0 seconds' in captured.err

    with kx.PyKXReimport():
        proc = subprocess.Popen(
            [q_exe_path, '-p', '15004'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    time.sleep(2)
    assert (await fut2) is None
    assert (await conn('10?`a`b`c`d')).py() is None
    assert (await conn('til 10')).py() == list(range(10))

    conn = await kx.AsyncQConnection(
        port=15004,
        reconnection_attempts=3,
        reconnection_delay=1.0,
        reconnection_function=lambda x: x,
        event_loop=event_loop
    )
    assert (await conn('til 20')).py() == list(range(20))
    proc.kill()
    time.sleep(2)

    with pytest.raises(BaseException):
        await conn('til 5')
    captured = capsys.readouterr()
    assert 'trying again in 0.5 seconds' not in captured.err
    assert 'trying again in 1.0 seconds' in captured.err
    assert 'trying again in 2.0 seconds' not in captured.err


@pytest.mark.asyncio
@pytest.mark.unlicensed
@pytest.mark.skipif(
    system() == 'Windows',
    reason='Subprocess requiring tests not currently operating on Windows consistently'
)
async def test_AsyncQConnection_proper_QFuture_hanlding(kx):
    q_exe_path = subprocess.run(['which', 'q'], stdout=subprocess.PIPE).stdout.decode().strip()

    q = [15100 + i for i in range(4)]
    with kx.PyKXReimport():
        procs = [subprocess.Popen(
            [q_exe_path, '-p', str(qp)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        ) for qp in q]
    time.sleep(2)

    async def async_query(port, qry):
        async with await kx.AsyncQConnection(port=port) as q:
            return await q(qry)
    qrys = [
        '{s:.z.p;system"sleep 2";(s;.z.p); til 10}[]',
        '{s:.z.p;system"sleep 5";(s;.z.p); til 20}[]',
        '{s:.z.p;system"sleep 1";(s;.z.p); til 5}[]',
        '{s:.z.p;system"sleep 3";(s;.z.p); til 7}[]',
    ]
    start = time.time()
    await asyncio.gather(*[asyncio.create_task(async_query(q[i], qrys[i])) for i in range(4)])
    end = time.time()
    assert end - start < 6.0
    [p.kill() for p in procs]
    time.sleep(2)


@pytest.mark.asyncio
@pytest.mark.unlicensed
async def test_async_reponse(kx, q_port):
    async with await kx.AsyncQConnection(port=q_port) as q:
        future1 = q(
            '{t: .z.p;while[.z.p < t+00:00:02; neg[.z.w]99]}[]',
            wait=False,
            reuse=False,
            async_response=True
        )
        future2 = await future1
        result = (await future2).py()
        assert result == 99
        with pytest.warns(UserWarning, match='Cannot use async_response=True without wait=False.'):
            q('{t: .z.p;while[.z.p < t+00:00:02; neg[.z.w]99]}[]', reuse=False, async_response=True)
        with pytest.warns(UserWarning, match='Cannot use async_response=True without reuse=False.'):
            q('{t: .z.p;while[.z.p < t+00:00:02; neg[.z.w]99]}[]', wait=False, async_response=True)

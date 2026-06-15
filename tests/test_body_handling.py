"""Comprehensive tests for request body size handling across all paths.

Covers:
- Normal body reading (core / ASGI / WSGI)
- Oversized body rejection (413)
- Stream mode body access
- json/form properties in stream mode
- Invalid / missing Content-Length
- Malformed JSON body
- Client disconnect during body read
"""
import asyncio
import io
import sys
import unittest

from microdot import Microdot, Request, Response, RequestError
from microdot.microdot import AsyncBytesIO
from microdot.test_client import TestClient
from tests.mock_socket import get_async_request_fd

# Default values for Request class attributes so tests can restore them
_DEFAULT_MAX_CONTENT_LENGTH = Request.max_content_length
_DEFAULT_MAX_BODY_LENGTH = Request.max_body_length


def _save_request_limits():
    return (Request.max_content_length, Request.max_body_length)


def _restore_request_limits(saved):
    Request.max_content_length = saved[0]
    Request.max_body_length = saved[1]


class TestRequestBodyCore(unittest.TestCase):
    """Tests for the core Request body handling (normal async path)."""

    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def setUp(self):
        # Always restore default limits before each test
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def tearDown(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    # ------------------------------------------------------------------
    # Normal requests
    # ------------------------------------------------------------------

    def test_normal_body_read(self):
        """A request with a body within limits is read into req.body."""
        app = Microdot()

        @app.post('/data')
        def handler(req):
            return 'received: ' + req.body.decode()

        client = TestClient(app)
        res = self._run(client.post('/data', body='hello'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, 'received: hello')

    def test_json_body(self):
        """JSON body is correctly parsed."""
        app = Microdot()

        @app.post('/json')
        def handler(req):
            data = req.json
            return str(data.get('key'))

        client = TestClient(app)
        res = self._run(client.post(
            '/json',
            headers={'Content-Type': 'application/json'},
            body='{"key": "value"}'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, 'value')

    def test_form_body(self):
        """Form body is correctly parsed."""
        app = Microdot()

        @app.post('/form')
        def handler(req):
            data = req.form
            return data['name']

        client = TestClient(app)
        res = self._run(client.post(
            '/form',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            body='name=alice&age=30'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, 'alice')

    def test_empty_body(self):
        """A request without a body works correctly."""
        app = Microdot()

        @app.get('/empty')
        def handler(req):
            self.assertEqual(req.body, b'')
            self.assertIsNone(req.json)
            self.assertIsNone(req.form)
            return 'ok'

        client = TestClient(app)
        res = self._run(client.get('/empty'))
        self.assertEqual(res.status_code, 200)

    # ------------------------------------------------------------------
    # Oversized body (413)
    # ------------------------------------------------------------------

    def test_oversized_body_returns_413(self):
        """A request exceeding max_content_length returns 413."""
        Request.max_content_length = 10
        Request.max_body_length = 10

        app = Microdot()

        @app.post('/upload')
        def handler(req):
            return 'should not reach here'

        client = TestClient(app)
        res = self._run(client.post('/upload', body='x' * 20))
        self.assertEqual(res.status_code, 413)
        self.assertIn('Payload too large', res.text)

    def test_body_within_content_length_but_over_body_length_uses_stream(self):
        """A body between max_body_length and max_content_length uses stream.
        """
        Request.max_content_length = 100
        Request.max_body_length = 5

        app = Microdot()

        @app.post('/stream')
        async def handler(req):
            # body should be empty, content available via stream
            self.assertEqual(req.body, b'')
            data = await req.stream.read(20)
            return 'streamed: ' + data.decode()

        client = TestClient(app)
        res = self._run(client.post('/stream', body='x' * 20))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, 'streamed: ' + 'x' * 20)

    # ------------------------------------------------------------------
    # Stream mode and json/form interaction
    # ------------------------------------------------------------------

    def test_json_in_stream_mode_raises_error(self):
        """Accessing req.json when body is in stream mode raises RequestError.
        """
        Request.max_content_length = 100
        Request.max_body_length = 5

        app = Microdot()

        @app.post('/json-stream')
        def handler(req):
            with self.assertRaises(RequestError) as ctx:
                _ = req.json
            self.assertEqual(ctx.exception.status_code, 400)
            return 'ok'

        client = TestClient(app)
        res = self._run(client.post(
            '/json-stream',
            headers={'Content-Type': 'application/json'},
            body='{"key": "value_that_is_long"}'))
        self.assertEqual(res.status_code, 200)

    def test_form_in_stream_mode_raises_error(self):
        """Accessing req.form when body is in stream mode raises RequestError.
        """
        Request.max_content_length = 100
        Request.max_body_length = 5

        app = Microdot()

        @app.post('/form-stream')
        def handler(req):
            with self.assertRaises(RequestError) as ctx:
                _ = req.form
            self.assertEqual(ctx.exception.status_code, 400)
            return 'ok'

        client = TestClient(app)
        res = self._run(client.post(
            '/form-stream',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            body='key=value_that_is_long'))
        self.assertEqual(res.status_code, 200)

    def test_json_on_oversized_body_returns_413(self):
        """Accessing req.json when body exceeds max_content_length gives 413.
        """
        Request.max_content_length = 10
        Request.max_body_length = 10

        app = Microdot()

        @app.post('/json-too-large')
        def handler(req):
            # dispatch_request already returns 413 before reaching here
            return 'should not reach here'

        client = TestClient(app)
        res = self._run(client.post(
            '/json-too-large',
            headers={'Content-Type': 'application/json'},
            body='{"key": "' + 'x' * 20 + '"}'))
        self.assertEqual(res.status_code, 413)

    # ------------------------------------------------------------------
    # Invalid Content-Length
    # ------------------------------------------------------------------

    def test_invalid_content_length_rejected(self):
        """A request with a non-numeric Content-Length is rejected with 400."""
        fd = get_async_request_fd('POST', '/foo', headers={
            'Content-Type': 'text/plain',
            'Content-Length': 'abc'}, body='hello')
        with self.assertRaises(RequestError) as ctx:
            self._run(Request.create('app', fd, 'writer', 'addr'))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('Content-Length', ctx.exception.reason)

    def test_negative_content_length_rejected(self):
        """A request with a negative Content-Length is rejected with 400."""
        fd = get_async_request_fd('POST', '/foo', headers={
            'Content-Type': 'text/plain',
            'Content-Length': '-5'}, body='hello')
        with self.assertRaises(RequestError) as ctx:
            self._run(Request.create('app', fd, 'writer', 'addr'))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_request_init_with_invalid_content_length(self):
        """Creating a Request with invalid Content-Length header raises
        RequestError."""
        from microdot.microdot import NoCaseDict
        headers = NoCaseDict({'Content-Length': 'not-a-number'})
        with self.assertRaises(RequestError) as ctx:
            Request('app', 'addr', 'POST', '/', '1.1', headers, body=b'')
        self.assertEqual(ctx.exception.status_code, 400)

    # ------------------------------------------------------------------
    # Malformed JSON body
    # ------------------------------------------------------------------

    def test_malformed_json_body(self):
        """Malformed JSON body raises RequestError when accessed."""
        app = Microdot()

        @app.post('/bad-json')
        def handler(req):
            with self.assertRaises(RequestError) as ctx:
                _ = req.json
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn('JSON', ctx.exception.reason)
            return 'ok'

        client = TestClient(app)
        res = self._run(client.post(
            '/bad-json',
            headers={'Content-Type': 'application/json'},
            body='{invalid json}'))
        self.assertEqual(res.status_code, 200)

    # ------------------------------------------------------------------
    # Body stream from body property (AsyncBytesIO wrapping)
    # ------------------------------------------------------------------

    def test_stream_from_body_property(self):
        """Accessing req.stream on a buffered request wraps body in
        AsyncBytesIO."""
        fd = get_async_request_fd('POST', '/foo', headers={
            'Content-Type': 'text/plain',
            'Content-Length': '5'}, body='hello')
        req = self._run(Request.create('app', fd, 'writer', 'addr'))
        self.assertEqual(req.body, b'hello')
        data = self._run(req.stream.read())
        self.assertEqual(data, b'hello')

    # ------------------------------------------------------------------
    # RequestError in dispatch_request (via handler)
    # ------------------------------------------------------------------

    def test_request_error_in_handler_produces_error_response(self):
        """RequestError raised in a handler produces a proper error response.
        """
        app = Microdot()

        @app.post('/raise')
        def handler(req):
            raise RequestError(400, 'Custom error message')

        client = TestClient(app)
        res = self._run(client.post('/raise', body='data'))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.text, 'Custom error message')

    # ------------------------------------------------------------------
    # Content-Length = 0
    # ------------------------------------------------------------------

    def test_zero_content_length(self):
        """A request with Content-Length: 0 works correctly."""
        fd = get_async_request_fd('POST', '/foo', headers={
            'Content-Type': 'text/plain',
            'Content-Length': '0'}, body='')
        req = self._run(Request.create('app', fd, 'writer', 'addr'))
        self.assertEqual(req.body, b'')
        self.assertEqual(req.content_length, 0)


@unittest.skipIf(sys.implementation.name == 'micropython',
                 'not supported under MicroPython')
class TestRequestBodyASGI(unittest.TestCase):
    """Tests for body handling in the ASGI path."""

    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def setUp(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def tearDown(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _make_scope(self, method='POST', path='/', headers=None,
                    content_length=None):
        scope = {
            'type': 'http',
            'path': path,
            'client': ['1.2.3.4', 1234],
            'method': method,
            'http_version': '1.1',
            'headers': [],
        }
        if headers:
            for k, v in headers.items():
                scope['headers'].append((k.lower().encode(), v.encode()))
        if content_length is not None:
            scope['headers'].append(
                (b'content-length', str(content_length).encode()))
        return scope

    def _make_receive_with_disconnect(self, body_chunks):
        """Receive that sends body chunks, then waits for a query before
        sending disconnect. This avoids racing with cancel_monitor."""
        idx = 0
        disconnect_delay = [False]

        async def receive():
            nonlocal idx
            if idx < len(body_chunks):
                chunk = body_chunks[idx]
                more = idx < len(body_chunks) - 1
                idx += 1
                return {'type': 'http.request', 'body': chunk,
                        'more_body': more}
            # Send disconnect only after a small delay so the response
            # sending has time to complete
            if not disconnect_delay[0]:
                disconnect_delay[0] = True
                await asyncio.sleep(0.1)
            return {'type': 'http.disconnect'}

        return receive

    def _collect_response(self):
        """Create an ASGI send callable that collects response data."""
        result = {'status': None, 'headers': [], 'body': b''}

        async def send(packet):
            if packet['type'] == 'http.response.start':
                result['status'] = packet['status']
                result['headers'] = packet.get('headers', [])
            elif packet['type'] == 'http.response.body':
                result['body'] += packet.get('body', b'')

        return result, send

    def test_asgi_normal_body(self):
        """Normal body reading works in ASGI mode."""
        from microdot.asgi import Microdot as ASGIMicrodot
        app = ASGIMicrodot()

        @app.post('/data')
        async def handler(req):
            return 'got: ' + req.body.decode()

        scope = self._make_scope(path='/data', content_length=5)
        receive = self._make_receive_with_disconnect([b'hello'])
        result, send = self._collect_response()

        self._run(app(scope, receive, send))
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body'], b'got: hello')

    def test_asgi_oversized_body_returns_413(self):
        """ASGI returns 413 for body exceeding max_content_length."""
        from microdot.asgi import Microdot as ASGIMicrodot

        Request.max_content_length = 10
        Request.max_body_length = 10

        app = ASGIMicrodot()

        @app.post('/upload')
        async def handler(req):
            return 'should not reach'

        scope = self._make_scope(path='/upload', content_length=20)
        receive = self._make_receive_with_disconnect([b'x' * 20])
        result, send = self._collect_response()

        self._run(app(scope, receive, send))
        self.assertEqual(result['status'], 413)

    def test_asgi_stream_mode(self):
        """ASGI uses stream mode when body > max_body_length."""
        from microdot.asgi import Microdot as ASGIMicrodot

        Request.max_content_length = 100
        Request.max_body_length = 5

        app = ASGIMicrodot()

        @app.post('/stream')
        async def handler(req):
            self.assertEqual(req.body, b'')
            data = await req.stream.read(20)
            return 'streamed: ' + data.decode()

        scope = self._make_scope(path='/stream', content_length=20)
        receive = self._make_receive_with_disconnect([b'x' * 20])
        result, send = self._collect_response()

        self._run(app(scope, receive, send))
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body'], b'streamed: ' + b'x' * 20)

    def test_asgi_invalid_content_length(self):
        """ASGI returns 400 for invalid Content-Length header."""
        from microdot.asgi import Microdot as ASGIMicrodot
        app = ASGIMicrodot()

        @app.post('/data')
        async def handler(req):
            return 'should not reach'

        scope = self._make_scope(path='/data')
        scope['headers'].append((b'content-length', b'not-a-number'))
        receive = self._make_receive_with_disconnect([b''])
        result, send = self._collect_response()

        self._run(app(scope, receive, send))
        self.assertEqual(result['status'], 400)

    def test_asgi_json_in_stream_mode_raises(self):
        """Accessing json in ASGI stream mode raises RequestError."""
        from microdot.asgi import Microdot as ASGIMicrodot

        Request.max_content_length = 100
        Request.max_body_length = 5

        app = ASGIMicrodot()

        @app.post('/json-stream')
        async def handler(req):
            try:
                _ = req.json
                return 'should have raised'
            except RequestError as e:
                return 'error: ' + str(e.status_code)

        scope = self._make_scope(
            path='/json-stream',
            headers={'Content-Type': 'application/json'},
            content_length=29)
        receive = self._make_receive_with_disconnect(
            [b'{"key": "value_that_is_long"}'])
        result, send = self._collect_response()

        self._run(app(scope, receive, send))
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body'], b'error: 400')


@unittest.skipIf(sys.implementation.name == 'micropython',
                 'not supported under MicroPython')
class TestRequestBodyWSGI(unittest.TestCase):
    """Tests for body handling in the WSGI path."""

    def setUp(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def tearDown(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def _make_environ(self, method='POST', path='/', headers=None,
                      body=b'', content_length=None):
        environ = {
            'SCRIPT_NAME': '',
            'PATH_INFO': path,
            'REMOTE_ADDR': '1.2.3.4',
            'REMOTE_PORT': '1234',
            'REQUEST_METHOD': method,
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'wsgi.input': io.BytesIO(body),
        }
        if headers:
            for k, v in headers.items():
                key = 'HTTP_' + k.upper().replace('-', '_')
                environ[key] = v
        if content_length is not None:
            environ['CONTENT_LENGTH'] = str(content_length)
        elif body:
            environ['CONTENT_LENGTH'] = str(len(body))
        return environ

    def test_wsgi_normal_body(self):
        """Normal body reading works in WSGI mode."""
        from microdot.wsgi import Microdot as WSGIMicrodot
        app = WSGIMicrodot()

        @app.post('/data')
        def handler(req):
            return 'got: ' + req.body.decode()

        environ = self._make_environ(path='/data', body=b'hello')
        result = {'status': None}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        body = b''.join(body_iter)
        self.assertEqual(result['status'], '200 OK')
        self.assertEqual(body, b'got: hello')

    def test_wsgi_oversized_body_returns_413(self):
        """WSGI returns 413 for body exceeding max_content_length."""
        from microdot.wsgi import Microdot as WSGIMicrodot

        Request.max_content_length = 10
        Request.max_body_length = 10

        app = WSGIMicrodot()

        @app.post('/upload')
        def handler(req):
            return 'should not reach'

        environ = self._make_environ(path='/upload', body=b'x' * 20)
        result = {'status': None}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        b''.join(body_iter)
        self.assertIn('413', result['status'])

    def test_wsgi_stream_mode(self):
        """WSGI uses stream mode when body > max_body_length."""
        from microdot.wsgi import Microdot as WSGIMicrodot

        Request.max_content_length = 100
        Request.max_body_length = 5

        app = WSGIMicrodot()

        @app.post('/stream')
        async def handler(req):
            self.assertEqual(req.body, b'')
            data = await req.stream.read(20)
            return 'streamed: ' + data.decode()

        environ = self._make_environ(path='/stream', body=b'x' * 20)
        result = {'status': None}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        body_data = b''.join(body_iter)
        self.assertEqual(result['status'], '200 OK')
        self.assertEqual(body_data, b'streamed: ' + b'x' * 20)

    def test_wsgi_invalid_content_length(self):
        """WSGI returns 400 for invalid Content-Length header."""
        from microdot.wsgi import Microdot as WSGIMicrodot
        app = WSGIMicrodot()

        @app.post('/data')
        def handler(req):
            return 'should not reach'

        environ = self._make_environ(
            path='/data', body=b'hello', content_length='abc')
        result = {'status': None, 'body': b''}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        result['body'] = b''.join(body_iter)
        self.assertIn('400', result['status'])

    def test_wsgi_zero_content_length(self):
        """WSGI handles Content-Length: 0 correctly."""
        from microdot.wsgi import Microdot as WSGIMicrodot
        app = WSGIMicrodot()

        @app.post('/empty')
        def handler(req):
            self.assertEqual(req.body, b'')
            self.assertEqual(req.content_length, 0)
            return 'ok'

        environ = self._make_environ(
            path='/empty', body=b'', content_length=0)
        result = {'status': None}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        b''.join(body_iter)
        self.assertEqual(result['status'], '200 OK')

    def test_wsgi_json_in_stream_mode_raises(self):
        """Accessing json in WSGI stream mode raises RequestError."""
        from microdot.wsgi import Microdot as WSGIMicrodot

        Request.max_content_length = 100
        Request.max_body_length = 5

        app = WSGIMicrodot()

        @app.post('/json-stream')
        async def handler(req):
            try:
                _ = req.json
                return 'should have raised'
            except RequestError as e:
                return 'error: ' + str(e.status_code)

        environ = self._make_environ(
            path='/json-stream',
            headers={'Content-Type': 'application/json'},
            body=b'{"key": "value_that_is_long"}')
        result = {'status': None}

        def start_response(status, headers):
            result['status'] = status

        body_iter = app(environ, start_response)
        body_data = b''.join(body_iter)
        self.assertEqual(result['status'], '200 OK')
        self.assertEqual(body_data, b'error: 400')


class TestRequestBodyConsistency(unittest.TestCase):
    """Test that behaviour is consistent across core/ASGI/WSGI paths."""

    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def setUp(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def tearDown(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def test_413_consistency(self):
        """All three paths return 413 for the same oversized request."""
        Request.max_content_length = 10
        Request.max_body_length = 10

        body_data = b'x' * 20

        # Core path via TestClient
        app1 = Microdot()

        @app1.post('/upload')
        def handler1(req):
            return 'nope'

        client = TestClient(app1)
        res = self._run(client.post('/upload', body=body_data))
        core_status = res.status_code

        # ASGI path
        from microdot.asgi import Microdot as ASGIMicrodot
        app2 = ASGIMicrodot()

        @app2.post('/upload')
        async def handler2(req):
            return 'nope'

        scope = {
            'type': 'http',
            'path': '/upload',
            'client': ['1.2.3.4', 1234],
            'method': 'POST',
            'http_version': '1.1',
            'headers': [(b'content-length', b'20')],
        }
        asgi_result = {'status': None}
        asgi_recv_idx = [0]

        async def asgi_receive_disconnect():
            if asgi_recv_idx[0] == 0:
                asgi_recv_idx[0] = 1
                return {'type': 'http.request', 'body': body_data,
                        'more_body': False}
            await asyncio.sleep(0.1)
            return {'type': 'http.disconnect'}

        async def asgi_send(packet):
            if packet['type'] == 'http.response.start':
                asgi_result['status'] = packet['status']

        self._run(app2(scope, asgi_receive_disconnect, asgi_send))
        asgi_status = asgi_result['status']

        # WSGI path
        from microdot.wsgi import Microdot as WSGIMicrodot
        app3 = WSGIMicrodot()

        @app3.post('/upload')
        def handler3(req):
            return 'nope'

        environ = {
            'SCRIPT_NAME': '',
            'PATH_INFO': '/upload',
            'REMOTE_ADDR': '1.2.3.4',
            'REMOTE_PORT': '1234',
            'REQUEST_METHOD': 'POST',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'CONTENT_LENGTH': '20',
            'wsgi.input': io.BytesIO(body_data),
        }
        wsgi_result = {'status': None}

        def start_response(status, headers):
            wsgi_result['status'] = status

        body_iter = app3(environ, start_response)
        b''.join(body_iter)
        wsgi_status_code = int(wsgi_result['status'].split()[0])

        # All three should agree
        self.assertEqual(core_status, 413)
        self.assertEqual(asgi_status, 413)
        self.assertEqual(wsgi_status_code, 413)

    def test_stream_mode_consistency(self):
        """Stream mode works the same across core and WSGI paths."""
        Request.max_content_length = 100
        Request.max_body_length = 5

        body_data = b'hello world!'

        # Core path
        app1 = Microdot()

        @app1.post('/stream')
        async def handler1(req):
            data = await req.stream.read(100)
            return data.decode()

        client = TestClient(app1)
        res = self._run(client.post('/stream', body=body_data))
        core_body = res.text

        # WSGI path
        from microdot.wsgi import Microdot as WSGIMicrodot
        app2 = WSGIMicrodot()

        @app2.post('/stream')
        async def handler2(req):
            data = await req.stream.read(100)
            return data.decode()

        environ = {
            'SCRIPT_NAME': '',
            'PATH_INFO': '/stream',
            'REMOTE_ADDR': '1.2.3.4',
            'REMOTE_PORT': '1234',
            'REQUEST_METHOD': 'POST',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'CONTENT_LENGTH': str(len(body_data)),
            'wsgi.input': io.BytesIO(body_data),
        }

        def start_response(status, headers):
            pass

        body_iter = app2(environ, start_response)
        wsgi_body = b''.join(body_iter)

        self.assertEqual(core_body, wsgi_body.decode())
        self.assertEqual(core_body, 'hello world!')


class TestRequestErrorHandling(unittest.TestCase):
    """Test that RequestError produces clean, debuggable responses."""

    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def setUp(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def tearDown(self):
        Request.max_content_length = _DEFAULT_MAX_CONTENT_LENGTH
        Request.max_body_length = _DEFAULT_MAX_BODY_LENGTH

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def test_error_response_includes_reason(self):
        """Error responses include the reason string in the body."""
        app = Microdot()

        @app.post('/data')
        def handler(req):
            raise RequestError(400, 'Missing required field')

        client = TestClient(app)
        res = self._run(client.post('/data', body='x'))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.text, 'Missing required field')

    def test_custom_error_handler_for_request_error(self):
        """A custom error handler can catch RequestError."""
        app = Microdot()

        @app.errorhandler(RequestError)
        def handle_request_error(req, exc):
            return {'error': exc.reason, 'code': exc.status_code}, \
                exc.status_code

        @app.post('/data')
        def handler(req):
            raise RequestError(400, 'bad input')

        client = TestClient(app)
        res = self._run(client.post('/data', body='x'))
        self.assertEqual(res.status_code, 400)
        self.assertIn('bad input', res.text)

    def test_413_error_handler(self):
        """The 413 error handler is invoked for oversized bodies."""
        Request.max_content_length = 10
        Request.max_body_length = 10

        app = Microdot()

        @app.errorhandler(413)
        def too_large(req):
            return 'File too big, sorry!', 413

        @app.post('/upload')
        def handler(req):
            return 'nope'

        client = TestClient(app)
        res = self._run(client.post('/upload', body='x' * 20))
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.text, 'File too big, sorry!')


if __name__ == '__main__':
    unittest.main()

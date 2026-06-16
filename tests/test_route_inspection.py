import io
import unittest
from microdot import Microdot


class TestRouteInspection(unittest.TestCase):
    def test_empty_app(self):
        """get_routes() returns empty list for app with no routes."""
        app = Microdot()
        self.assertEqual(app.get_routes(), [])

    def test_empty_app_print_routes(self):
        """print_routes() handles empty app gracefully."""
        app = Microdot()
        buf = io.StringIO()
        app.print_routes(file=buf)
        output = buf.getvalue()
        self.assertIn('No routes registered', output)

    def test_single_static_route(self):
        """get_routes() returns correct info for a single static route."""
        app = Microdot()

        @app.route('/')
        def index(req):
            return 'hello'

        routes = app.get_routes()
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r['methods'], ['GET'])
        self.assertEqual(r['path'], '/')
        self.assertEqual(r['handler'], 'index')
        self.assertFalse(r['is_dynamic'])
        self.assertEqual(r['dynamic_params'], [])
        self.assertEqual(r['url_prefix'], '')
        self.assertIsNone(r['subapp'])
        self.assertEqual(r['warnings'], [])

    def test_dynamic_route(self):
        """get_routes() identifies dynamic routes and their params."""
        app = Microdot()

        @app.route('/users/<int:id>')
        def get_user(req, id):
            return str(id)

        @app.route('/files/<path:filepath>')
        def get_file(req, filepath):
            return filepath

        routes = app.get_routes()
        self.assertEqual(len(routes), 2)

        r = routes[0]
        self.assertTrue(r['is_dynamic'])
        self.assertEqual(r['dynamic_params'], ['id'])
        self.assertEqual(r['path'], '/users/<int:id>')

        r = routes[1]
        self.assertTrue(r['is_dynamic'])
        self.assertEqual(r['dynamic_params'], ['filepath'])

    def test_multiple_methods(self):
        """get_routes() correctly reports routes with multiple methods."""
        app = Microdot()

        @app.route('/data', methods=['GET', 'POST'])
        def handle_data(req):
            return 'data'

        routes = app.get_routes()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]['methods'], ['GET', 'POST'])

    def test_multiple_methods_separate_routes(self):
        """get_routes() handles same path with different methods."""
        app = Microdot()

        @app.get('/items')
        def get_items(req):
            return 'get'

        @app.post('/items')
        def create_item(req):
            return 'post'

        routes = app.get_routes()
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0]['methods'], ['GET'])
        self.assertEqual(routes[0]['handler'], 'get_items')
        self.assertEqual(routes[1]['methods'], ['POST'])
        self.assertEqual(routes[1]['handler'], 'create_item')

    def test_subapp_prefix(self):
        """get_routes() includes full path with prefix for mounted sub-apps."""
        app = Microdot()
        sub = Microdot()

        @sub.route('/')
        def sub_index(req):
            return 'sub'

        @sub.route('/detail/<int:id>')
        def sub_detail(req, id):
            return str(id)

        app.mount(sub, url_prefix='/api')

        routes = app.get_routes()
        self.assertEqual(len(routes), 2)

        r = routes[0]
        self.assertEqual(r['path'], '/api/')
        self.assertEqual(r['url_prefix'], '/api')
        self.assertIsNotNone(r['subapp'])
        self.assertFalse(r['is_dynamic'])

        r = routes[1]
        self.assertEqual(r['path'], '/api/detail/<int:id>')
        self.assertEqual(r['url_prefix'], '/api')
        self.assertTrue(r['is_dynamic'])
        self.assertEqual(r['dynamic_params'], ['id'])

    def test_duplicate_route_warning(self):
        """get_routes() warns when the same method+path is registered twice."""
        app = Microdot()

        @app.get('/dup')
        def handler_a(req):
            return 'a'

        @app.get('/dup')
        def handler_b(req):
            return 'b'

        routes = app.get_routes()
        self.assertEqual(len(routes), 2)
        # Both routes should have warnings
        self.assertTrue(len(routes[0]['warnings']) > 0)
        self.assertTrue(len(routes[1]['warnings']) > 0)
        self.assertIn('Duplicate', routes[1]['warnings'][0])
        self.assertIn('handler_a', routes[1]['warnings'][0])

    def test_no_warning_for_different_methods(self):
        """Same path but different methods should not trigger warnings."""
        app = Microdot()

        @app.get('/ok')
        def get_ok(req):
            return 'get'

        @app.post('/ok')
        def post_ok(req):
            return 'post'

        routes = app.get_routes()
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0]['warnings'], [])
        self.assertEqual(routes[1]['warnings'], [])

    def test_print_routes_output(self):
        """print_routes() produces formatted table output."""
        app = Microdot()

        @app.get('/hello')
        def hello(req):
            return 'hi'

        @app.route('/users/<int:id>', methods=['GET', 'PUT'])
        def user(req, id):
            return str(id)

        buf = io.StringIO()
        app.print_routes(file=buf)
        output = buf.getvalue()

        self.assertIn('Methods', output)
        self.assertIn('Path', output)
        self.assertIn('Handler', output)
        self.assertIn('GET', output)
        self.assertIn('/hello', output)
        self.assertIn('hello', output)
        self.assertIn('/users/<int:id>', output)
        self.assertIn('user', output)
        self.assertIn('dynamic', output)

    def test_print_routes_with_subapp(self):
        """print_routes() shows prefix info for sub-apps."""
        app = Microdot()
        sub = Microdot()

        @sub.get('/list')
        def list_items(req):
            return 'list'

        app.mount(sub, url_prefix='/api/v1')

        buf = io.StringIO()
        app.print_routes(file=buf)
        output = buf.getvalue()

        self.assertIn('/api/v1/list', output)
        self.assertIn('prefix:/api/v1', output)

    def test_print_routes_with_warnings(self):
        """print_routes() includes warnings in output."""
        app = Microdot()

        @app.get('/dup')
        def first(req):
            return 'first'

        @app.get('/dup')
        def second(req):
            return 'second'

        buf = io.StringIO()
        app.print_routes(file=buf)
        output = buf.getvalue()

        self.assertIn('WARNING', output)
        self.assertIn('Duplicate', output)

    def test_http_shortcut_methods(self):
        """get_routes() works with get/post/put/patch/delete shortcuts."""
        app = Microdot()

        @app.get('/r1')
        def r1(req):
            return ''

        @app.post('/r2')
        def r2(req):
            return ''

        @app.put('/r3')
        def r3(req):
            return ''

        @app.patch('/r4')
        def r4(req):
            return ''

        @app.delete('/r5')
        def r5(req):
            return ''

        routes = app.get_routes()
        self.assertEqual(len(routes), 5)
        self.assertEqual(routes[0]['methods'], ['GET'])
        self.assertEqual(routes[1]['methods'], ['POST'])
        self.assertEqual(routes[2]['methods'], ['PUT'])
        self.assertEqual(routes[3]['methods'], ['PATCH'])
        self.assertEqual(routes[4]['methods'], ['DELETE'])

    def test_mixed_static_and_dynamic_routes(self):
        """get_routes() correctly classifies mixed routes."""
        app = Microdot()

        @app.get('/static/path')
        def static_handler(req):
            return ''

        @app.get('/dynamic/<name>/<int:id>')
        def dynamic_handler(req, name, id):
            return ''

        routes = app.get_routes()
        self.assertFalse(routes[0]['is_dynamic'])
        self.assertEqual(routes[0]['dynamic_params'], [])
        self.assertTrue(routes[1]['is_dynamic'])
        self.assertEqual(routes[1]['dynamic_params'], ['name', 'id'])

    def test_subapp_without_prefix(self):
        """get_routes() handles sub-apps mounted without prefix."""
        app = Microdot()
        sub = Microdot()

        @sub.get('/items')
        def items(req):
            return ''

        app.mount(sub)

        routes = app.get_routes()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]['path'], '/items')
        self.assertEqual(routes[0]['url_prefix'], '')
        self.assertIsNotNone(routes[0]['subapp'])


if __name__ == '__main__':
    unittest.main()

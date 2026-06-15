import unittest
from microdot import Microdot


class TestRouteInspection(unittest.TestCase):
    def test_empty_app(self):
        app = Microdot()
        self.assertEqual(app.list_routes(), [])
        self.assertEqual(app.check_routes(), [])
        self.assertIn('no routes', app.print_routes())

    def test_static_route(self):
        app = Microdot()

        @app.route('/')
        def index(req):
            return 'x'

        routes = app.list_routes()
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route['path'], '/')
        self.assertEqual(route['methods'], ['GET'])
        self.assertEqual(route['handler'], 'index')
        self.assertFalse(route['dynamic'])
        self.assertEqual(route['params'], [])
        self.assertFalse(route['mounted'])
        self.assertEqual(route['url_prefix'], '')

    def test_multiple_methods(self):
        app = Microdot()

        @app.route('/invoices', methods=['POST', 'GET'])
        def invoices(req):
            return 'x'

        @app.post('/invoices/new')
        def new_invoice(req):
            return 'x'

        routes = {r['path']: r for r in app.list_routes()}
        # methods are reported in sorted order regardless of registration order
        self.assertEqual(routes['/invoices']['methods'], ['GET', 'POST'])
        self.assertEqual(routes['/invoices/new']['methods'], ['POST'])
        # different paths are never flagged as shadowing each other
        self.assertEqual(app.check_routes(), [])

    def test_split_methods_same_path_is_allowed(self):
        app = Microdot()

        @app.get('/resource')
        def get_resource(req):
            return 'x'

        @app.post('/resource')
        def create_resource(req):
            return 'x'

        # GET and POST on the same path via two routes is a valid pattern
        self.assertEqual(app.check_routes(), [])

    def test_dynamic_route(self):
        app = Microdot()

        @app.get('/users/<int:id>/posts/<slug>')
        def user_post(req, id, slug):
            return 'x'

        @app.get('/files/<path:p>')
        def files(req, p):
            return 'x'

        @app.get('/code/<re:[a-c]+:val>')
        def code(req, val):
            return 'x'

        routes = {r['path']: r for r in app.list_routes()}

        first = routes['/users/<int:id>/posts/<slug>']
        self.assertTrue(first['dynamic'])
        self.assertEqual(first['params'], [
            {'name': 'id', 'type': 'int'},
            {'name': 'slug', 'type': 'string'},
        ])

        self.assertEqual(routes['/files/<path:p>']['params'],
                         [{'name': 'p', 'type': 'path'}])

        self.assertEqual(routes['/code/<re:[a-c]+:val>']['params'],
                         [{'name': 'val', 'type': 're', 'pattern': '[a-c]+'}])

    def test_mounted_subapp(self):
        subapp = Microdot()

        @subapp.get('/')
        def home(req):
            return 'x'

        @subapp.get('/item/<int:id>')
        def item(req, id):
            return 'x'

        app = Microdot()

        @app.get('/')
        def root(req):
            return 'x'

        app.mount(subapp, url_prefix='/sub')

        routes = {r['path']: r for r in app.list_routes()}

        # the top-level route is not marked as mounted
        self.assertIn('/', routes)
        self.assertFalse(routes['/']['mounted'])
        self.assertEqual(routes['/']['url_prefix'], '')

        # mounted routes expose the full path, including the prefix
        self.assertIn('/sub/', routes)
        self.assertTrue(routes['/sub/']['mounted'])
        self.assertEqual(routes['/sub/']['url_prefix'], '/sub')

        nested = routes['/sub/item/<int:id>']
        self.assertTrue(nested['mounted'])
        self.assertTrue(nested['dynamic'])
        self.assertEqual(nested['url_prefix'], '/sub')
        self.assertEqual(nested['params'], [{'name': 'id', 'type': 'int'}])

    def test_check_duplicate_routes(self):
        app = Microdot()

        @app.get('/dup')
        def first(req):
            return 'x'

        @app.get('/dup')
        def second(req):
            return 'x'

        warnings = app.check_routes()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['path'], '/dup')
        self.assertEqual(warnings[0]['methods'], ['GET'])
        self.assertIn('shadowed', warnings[0]['message'])

    def test_check_dynamic_shadow(self):
        app = Microdot()

        @app.get('/users/<id>')
        def by_id(req, id):
            return 'x'

        @app.get('/users/<name>')
        def by_name(req, name):
            return 'x'

        warnings = app.check_routes()
        self.assertEqual(len(warnings), 1)
        self.assertIn('shadowed', warnings[0]['message'])

    def test_check_no_false_positive_for_different_types(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        def by_id(req, id):
            return 'x'

        @app.get('/users/<name>')
        def by_name(req, name):
            return 'x'

        # an int segment and a string segment match different paths
        self.assertEqual(app.check_routes(), [])

    def test_check_duplicate_method_in_list(self):
        app = Microdot()

        @app.route('/y', methods=['GET', 'GET'])
        def handler(req):
            return 'x'

        warnings = app.check_routes()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['methods'], ['GET'])
        self.assertIn('duplicate methods', warnings[0]['message'])

    def test_print_routes_format(self):
        app = Microdot()

        @app.get('/')
        def index(req):
            return 'x'

        @app.post('/users/<int:id>')
        def update(req, id):
            return 'x'

        text = app.print_routes()
        self.assertIn('METHOD', text)
        self.assertIn('PATH', text)
        self.assertIn('HANDLER', text)
        self.assertIn('/users/<int:id>', text)
        self.assertIn('index', text)
        self.assertIn('[dynamic]', text)


if __name__ == '__main__':
    unittest.main()

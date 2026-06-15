import json
import unittest

from microdot import Microdot
from microdot.openapi import (
    get_routes, get_openapi, get_openapi_json, openapi,
    _url_pattern_to_openapi,
)
from microdot.microdot import URLPattern


class TestUrlPatternToOpenapi(unittest.TestCase):
    def test_static_path(self):
        p = URLPattern('/users')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/users')
        self.assertEqual(params, [])

    def test_root_path(self):
        p = URLPattern('/')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/')
        self.assertEqual(params, [])

    def test_dynamic_string_segment(self):
        p = URLPattern('/users/<name>')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/users/{name}')
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]['name'], 'name')
        self.assertEqual(params[0]['in'], 'path')
        self.assertTrue(params[0]['required'])
        self.assertEqual(params[0]['schema'], {'type': 'string'})

    def test_dynamic_int_segment(self):
        p = URLPattern('/users/<int:id>')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/users/{id}')
        self.assertEqual(params[0]['schema'], {'type': 'integer'})

    def test_dynamic_path_segment(self):
        p = URLPattern('/files/<path:filepath>')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/files/{filepath}')
        self.assertEqual(params[0]['schema'], {'type': 'string'})

    def test_regex_segment(self):
        p = URLPattern('/items/<re:[a-z]+:slug>')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/items/{slug}')
        self.assertEqual(params[0]['schema'], {'type': 'string'})

    def test_multiple_segments(self):
        p = URLPattern('/users/<int:user_id>/posts/<int:post_id>')
        path, params = _url_pattern_to_openapi(p)
        self.assertEqual(path, '/users/{user_id}/posts/{post_id}')
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0]['name'], 'user_id')
        self.assertEqual(params[1]['name'], 'post_id')


class TestGetRoutes(unittest.TestCase):
    def test_empty_app(self):
        app = Microdot()
        self.assertEqual(get_routes(app), [])

    def test_simple_get_route(self):
        app = Microdot()

        @app.route('/')
        def index(req):
            """Home page"""
            return 'hi'

        routes = get_routes(app)
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r['methods'], ['GET'])
        self.assertEqual(r['path'], '/')
        self.assertEqual(r['openapi_path'], '/')
        self.assertEqual(r['parameters'], [])
        self.assertEqual(r['endpoint'], 'index')
        self.assertEqual(r['summary'], 'Home page')
        self.assertIn('200', r['responses'])

    def test_route_with_parameters(self):
        app = Microdot()

        @app.route('/users/<int:id>')
        def get_user(req, id):
            """Retrieve a user."""
            return {}

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['openapi_path'], '/users/{id}')
        self.assertEqual(len(r['parameters']), 1)
        self.assertEqual(r['parameters'][0]['name'], 'id')
        self.assertEqual(r['parameters'][0]['schema']['type'], 'integer')

    def test_multiple_methods(self):
        app = Microdot()

        @app.route('/items', methods=['GET', 'POST'])
        def items(req):
            return ''

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['methods'], ['GET', 'POST'])
        # POST default 201, GET default 200
        self.assertIn('200', r['responses'])
        self.assertIn('201', r['responses'])

    def test_post_default_response(self):
        app = Microdot()

        @app.post('/items')
        def create_item(req):
            return '', 201

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['methods'], ['POST'])
        self.assertIn('201', r['responses'])

    def test_delete_default_response(self):
        app = Microdot()

        @app.delete('/items/<int:id>')
        def delete_item(req, id):
            return '', 204

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['methods'], ['DELETE'])
        self.assertIn('204', r['responses'])

    def test_handler_name_as_summary_fallback(self):
        app = Microdot()

        @app.route('/no-docs')
        def my_handler(req):
            return ''

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['summary'], 'my_handler')
        self.assertEqual(r['description'], '')

    def test_multiline_docstring(self):
        app = Microdot()

        @app.route('/info')
        def info(req):
            """Summary line.

            More detailed description here.
            """
            return ''

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['summary'], 'Summary line.')
        self.assertIn('More detailed', r['description'])

    def test_openapi_decorator_overrides(self):
        app = Microdot()

        @app.get('/items/<int:id>')
        @openapi(
            summary='Get an item',
            description='Retrieve an item by its ID.',
            responses={200: {'description': 'An item'},
                       404: {'description': 'Not found'}},
        )
        def get_item(req, id):
            """This docstring is ignored because of the decorator."""
            return {}

        routes = get_routes(app)
        r = routes[0]
        self.assertEqual(r['summary'], 'Get an item')
        self.assertEqual(r['description'], 'Retrieve an item by its ID.')
        self.assertIn('200', r['responses'])
        self.assertIn('404', r['responses'])
        self.assertEqual(r['responses']['404']['description'], 'Not found')

    def test_subapp_routes(self):
        app = Microdot()
        sub = Microdot()

        @sub.route('/sub-item')
        def sub_item(req):
            """Sub item."""
            return ''

        app.mount(sub, url_prefix='/api')
        routes = get_routes(app)
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r['path'], '/api/sub-item')
        self.assertEqual(r['openapi_path'], '/api/sub-item')


class TestGetOpenapi(unittest.TestCase):
    def test_basic_spec(self):
        app = Microdot()

        @app.route('/hello')
        def hello(req):
            """Say hello."""
            return 'hello'

        spec = get_openapi(app, title='Test API', version='0.1.0')
        self.assertEqual(spec['openapi'], '3.0.3')
        self.assertEqual(spec['info']['title'], 'Test API')
        self.assertEqual(spec['info']['version'], '0.1.0')
        self.assertIn('/hello', spec['paths'])
        self.assertIn('get', spec['paths']['/hello'])

    def test_path_parameters_in_spec(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        def get_user(req, id):
            """Get user."""
            return {}

        spec = get_openapi(app)
        path = spec['paths']['/users/{id}']
        self.assertIn('get', path)
        op = path['get']
        self.assertEqual(len(op['parameters']), 1)
        self.assertEqual(op['parameters'][0]['name'], 'id')

    def test_multiple_methods_same_path(self):
        app = Microdot()

        @app.route('/items', methods=['GET', 'POST'])
        def items(req):
            return ''

        spec = get_openapi(app)
        path = spec['paths']['/items']
        self.assertIn('get', path)
        self.assertIn('post', path)
        # Same operation object is referenced for both methods
        self.assertIs(path['get'], path['post'])

    def test_description_included(self):
        app = Microdot()
        spec = get_openapi(app, description='My API description')
        self.assertEqual(spec['info']['description'], 'My API description')

    def test_description_omitted_when_empty(self):
        app = Microdot()
        spec = get_openapi(app)
        self.assertFalse('description' in spec['info'])

    def test_empty_app_spec(self):
        app = Microdot()
        spec = get_openapi(app)
        self.assertEqual(spec['paths'], {})


class TestGetOpenapiJson(unittest.TestCase):
    def test_returns_json_string(self):
        app = Microdot()

        @app.route('/ping')
        def ping(req):
            return 'pong'

        raw = get_openapi_json(app, title='JSON API')
        parsed = json.loads(raw)
        self.assertEqual(parsed['info']['title'], 'JSON API')
        self.assertIn('/ping', parsed['paths'])

    def test_roundtrip_matches_dict(self):
        app = Microdot()

        @app.get('/a/<x>')
        def a(req, x):
            return x

        spec_dict = get_openapi(app)
        spec_json = json.loads(get_openapi_json(app))
        self.assertEqual(spec_dict, spec_json)


class TestOpenapiDecorator(unittest.TestCase):
    def test_decorator_attaches_metadata(self):
        @openapi(summary='s', description='d', responses={200: {}})
        def handler(req):
            return ''

        self.assertEqual(handler.openapi['summary'], 's')
        self.assertEqual(handler.openapi['description'], 'd')
        self.assertEqual(handler.openapi['responses'], {200: {}})

    def test_decorator_defaults_to_none(self):
        @openapi()
        def handler(req):
            return ''

        self.assertIsNone(handler.openapi['summary'])
        self.assertIsNone(handler.openapi['description'])
        self.assertIsNone(handler.openapi['responses'])

    def test_decorator_preserves_function(self):
        @openapi(summary='x')
        def handler(req):
            return 'ok'

        # Function should still be callable and unchanged in behaviour.
        self.assertEqual(handler(None), 'ok')
        self.assertEqual(handler.__name__, 'handler')


if __name__ == '__main__':
    unittest.main()

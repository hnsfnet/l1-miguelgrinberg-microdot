import json
import unittest
from microdot import Microdot
from microdot.openapi import describe_routes, generate_openapi, \
    generate_openapi_json, openapi


class TestOpenAPI(unittest.TestCase):
    def test_describe_empty_app(self):
        app = Microdot()
        self.assertEqual(describe_routes(app), [])

    def test_describe_simple_route(self):
        app = Microdot()

        @app.route('/')
        def index(request):
            """Return the home page."""
            return 'hello'

        routes = describe_routes(app)
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route['path'], '/')
        self.assertEqual(route['openapi_path'], '/')
        self.assertEqual(route['methods'], ['GET'])
        self.assertEqual(route['parameters'], [])
        self.assertEqual(route['handler'], 'index')
        self.assertEqual(route['summary'], 'Return the home page.')

    def test_describe_route_with_parameter(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        def get_user(request, id):
            return {}

        route = describe_routes(app)[0]
        self.assertEqual(route['path'], '/users/<int:id>')
        self.assertEqual(route['openapi_path'], '/users/{id}')
        self.assertEqual(route['methods'], ['GET'])
        self.assertEqual(route['parameters'], [
            {'name': 'id', 'type': 'int', 'in': 'path', 'required': True},
        ])

    def test_describe_route_with_many_parameters(self):
        app = Microdot()

        @app.get('/<string:name>/<path:rest>/<re:[0-9]+:code>')
        def handler(request, name, rest, code):
            return ''

        route = describe_routes(app)[0]
        self.assertEqual(route['openapi_path'],
                         '/{name}/{rest}/{code}')
        self.assertEqual([p['name'] for p in route['parameters']],
                         ['name', 'rest', 'code'])
        self.assertEqual([p['type'] for p in route['parameters']],
                         ['string', 'path', 're:[0-9]+'])

    def test_describe_default_string_parameter(self):
        app = Microdot()

        @app.get('/items/<id>')
        def handler(request, id):
            return ''

        route = describe_routes(app)[0]
        self.assertEqual(route['parameters'], [
            {'name': 'id', 'type': 'string', 'in': 'path',
             'required': True},
        ])

    def test_describe_multiple_methods(self):
        app = Microdot()

        @app.route('/users', methods=['GET', 'POST'])
        def users(request):
            return ''

        route = describe_routes(app)[0]
        self.assertEqual(route['methods'], ['GET', 'POST'])

    def test_describe_no_docstring(self):
        app = Microdot()

        @app.get('/')
        def index(request):
            return ''

        route = describe_routes(app)[0]
        self.assertIsNone(route['summary'])
        self.assertIsNone(route['description'])

    def test_openapi_empty_app(self):
        app = Microdot()
        spec = generate_openapi(app)
        self.assertEqual(spec['openapi'], '3.1.0')
        self.assertEqual(spec['info'], {'title': 'Microdot API',
                                        'version': '1.0.0'})
        self.assertEqual(spec['paths'], {})

    def test_openapi_info_options(self):
        app = Microdot()
        spec = generate_openapi(app, title='My API', version='2.3.4',
                                description='A test API',
                                servers=[{'url': 'https://example.com'}],
                                openapi_version='3.0.3')
        self.assertEqual(spec['openapi'], '3.0.3')
        self.assertEqual(spec['info'], {
            'title': 'My API', 'version': '2.3.4',
            'description': 'A test API'})
        self.assertEqual(spec['servers'], [{'url': 'https://example.com'}])

    def test_openapi_simple_route(self):
        app = Microdot()

        @app.get('/')
        def index(request):
            """Get the home page."""
            return ''

        spec = generate_openapi(app)
        self.assertIn('/', spec['paths'])
        op = spec['paths']['/']['get']
        self.assertEqual(op['summary'], 'Get the home page.')
        self.assertEqual(op['operationId'], 'index')
        self.assertEqual(op['responses'],
                         {'200': {'description': 'Successful response'}})
        self.assertNotIn('parameters', op)
        # a single line docstring only sets the summary
        self.assertNotIn('description', op)

    def test_openapi_multiline_docstring(self):
        app = Microdot()

        @app.get('/')
        def index(request):
            """Get the home page.

            A longer explanation of what this does.
            """
            return ''

        op = generate_openapi(app)['paths']['/']['get']
        self.assertEqual(op['summary'], 'Get the home page.')
        self.assertIn('longer explanation', op['description'])

    def test_openapi_path_parameters(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        def get_user(request, id):
            return ''

        op = generate_openapi(app)['paths']['/users/{id}']['get']
        self.assertEqual(op['parameters'], [{
            'name': 'id', 'in': 'path', 'required': True,
            'schema': {'type': 'integer'},
        }])

    def test_openapi_regex_parameter_schema(self):
        app = Microdot()

        @app.get('/users/<re:[a-c]+:id>')
        def get_user(request, id):
            return ''

        op = generate_openapi(app)['paths']['/users/{id}']['get']
        self.assertEqual(op['parameters'][0]['schema'],
                         {'type': 'string', 'pattern': '[a-c]+'})

    def test_openapi_multiple_methods_grouped(self):
        app = Microdot()

        @app.route('/users', methods=['GET', 'POST'])
        def users(request):
            return ''

        path_item = generate_openapi(app)['paths']['/users']
        self.assertIn('get', path_item)
        self.assertIn('post', path_item)
        # the two operations must have unique operation ids
        self.assertNotEqual(path_item['get']['operationId'],
                            path_item['post']['operationId'])

    def test_openapi_unique_operation_ids(self):
        app = Microdot()

        @app.get('/a')
        def handler(request):
            return ''

        @app.post('/b')
        def handler(request):  # noqa: F811 (intentional name reuse)
            return ''

        spec = generate_openapi(app)
        ids = [spec['paths']['/a']['get']['operationId'],
               spec['paths']['/b']['post']['operationId']]
        self.assertEqual(len(set(ids)), 2)

    def test_openapi_decorator_metadata(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        @openapi(summary='Fetch a user', tags=['users'],
                 operation_id='fetchUser',
                 responses={'200': {'description': 'The user'},
                            '404': {'description': 'Not found'}})
        def get_user(request, id):
            """This docstring is overridden by the decorator."""
            return ''

        op = generate_openapi(app)['paths']['/users/{id}']['get']
        self.assertEqual(op['summary'], 'Fetch a user')
        self.assertEqual(op['tags'], ['users'])
        self.assertEqual(op['operationId'], 'fetchUser')
        self.assertEqual(op['responses'], {
            '200': {'description': 'The user'},
            '404': {'description': 'Not found'}})
        # path parameters are still derived automatically
        self.assertEqual(op['parameters'][0]['name'], 'id')

    def test_openapi_decorator_does_not_break_routing(self):
        app = Microdot()

        @app.get('/')
        @openapi(summary='Home')
        def index(request):
            return ''

        # the handler stored in the url map is still the original function
        handler = app.url_map[0][2]
        self.assertTrue(callable(handler))
        self.assertEqual(handler.__name__, 'index')

    def test_openapi_decorator_request_body_and_parameters(self):
        app = Microdot()

        body = {'content': {'application/json': {'schema': {}}}}
        params = [{'name': 'q', 'in': 'query', 'schema': {'type': 'string'}}]

        @app.post('/search')
        @openapi(request_body=body, parameters=params)
        def search(request):
            return ''

        op = generate_openapi(app)['paths']['/search']['post']
        self.assertEqual(op['requestBody'], body)
        self.assertEqual(op['parameters'], params)

    def test_openapi_mounted_subapp(self):
        app = Microdot()
        subapp = Microdot()

        @subapp.get('/items/<int:id>')
        def get_item(request, id):
            return ''

        app.mount(subapp, url_prefix='/api')

        spec = generate_openapi(app)
        self.assertIn('/api/items/{id}', spec['paths'])
        op = spec['paths']['/api/items/{id}']['get']
        self.assertEqual(op['parameters'][0]['name'], 'id')

    def test_generate_openapi_json(self):
        app = Microdot()

        @app.get('/users/<int:id>')
        def get_user(request, id):
            """Get a user."""
            return ''

        text = generate_openapi_json(app, title='My API')
        self.assertIsInstance(text, str)
        spec = json.loads(text)
        self.assertEqual(spec['info']['title'], 'My API')
        self.assertEqual(
            spec['paths']['/users/{id}']['get']['summary'], 'Get a user.')

    def test_generate_openapi_json_compact(self):
        app = Microdot()

        @app.get('/')
        def index(request):
            return ''

        text = generate_openapi_json(app, indent=None)
        # compact output has no newlines
        self.assertNotIn('\n', text)
        self.assertEqual(json.loads(text)['paths']['/']['get']['operationId'],
                         'index')


if __name__ == '__main__':
    unittest.main()

from microdot import Microdot
from microdot.openapi import describe_routes, generate_openapi, openapi

app = Microdot()


@app.get('/')
def index(request):
    """Return a welcome message."""
    return 'Hello, world!'


@app.get('/users')
def list_users(request):
    """List all users."""
    return [{'id': 1, 'name': 'Susan'}]


@app.get('/users/<int:id>')
@openapi(summary='Get a single user',
         responses={'200': {'description': 'The requested user'},
                    '404': {'description': 'User not found'}})
def get_user(request, id):
    return {'id': id, 'name': 'Susan'}


@app.post('/users')
@openapi(summary='Create a user', tags=['users'])
def create_user(request):
    """Create a new user from the submitted JSON body."""
    return request.json, 201


@app.get('/openapi.json')
def openapi_spec(request):
    """Serve the OpenAPI document for this application."""
    return generate_openapi(app, title='Users API', version='1.0.0',
                            description='A tiny example API.')


if __name__ == '__main__':
    # print a readable summary of the registered routes on startup
    for route in describe_routes(app):
        print('{methods} {path}'.format(
            methods=','.join(route['methods']), path=route['path']))
    app.run(debug=True)

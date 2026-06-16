"""
Example demonstrating route inspection in Microdot.

This example shows how to use the get_routes() and print_routes() methods
to inspect registered routes for debugging and documentation purposes.
"""
from microdot import Microdot

app = Microdot()


@app.get('/')
async def index(request):
    return 'Welcome to the API!'


@app.get('/users/<int:id>')
async def get_user(request, id):
    return {'user_id': id}


@app.post('/users')
async def create_user(request):
    return {'created': True}, 201


@app.route('/items', methods=['GET', 'POST'])
async def handle_items(request):
    if request.method == 'GET':
        return {'items': []}
    else:
        return {'created': True}, 201


# Create a sub-application for API v2
api_v2 = Microdot()


@api_v2.get('/products')
async def list_products(request):
    return {'products': []}


@api_v2.get('/products/<int:id>')
async def get_product(request, id):
    return {'product_id': id}


# Mount the sub-application with a prefix
app.mount(api_v2, url_prefix='/api/v2')

if __name__ == '__main__':
    print("=" * 60)
    print("Route Inspection Example")
    print("=" * 60)
    print()

    # Method 1: Print formatted table
    print("Using print_routes():")
    print("-" * 60)
    app.print_routes()
    print()

    # Method 2: Get structured data
    print("Using get_routes():")
    print("-" * 60)
    routes = app.get_routes()
    for route in routes:
        methods_str = ', '.join(route['methods'])
        print(f"{methods_str:12} {route['path']:30} -> {route['handler']}")
        if route['is_dynamic']:
            print(f"{'':12} Dynamic params: {route['dynamic_params']}")
        if route['url_prefix']:
            print(f"{'':12} URL prefix: {route['url_prefix']}")
    print()

    # Method 3: Use for documentation generation
    print("Generating simple API documentation:")
    print("-" * 60)
    print("# API Endpoints")
    print()
    for route in routes:
        methods_str = ', '.join(route['methods'])
        print(f"## {methods_str} {route['path']}")
        print(f"Handler: `{route['handler']}`")
        if route['dynamic_params']:
            print(f"Parameters: {', '.join(route['dynamic_params'])}")
        print()

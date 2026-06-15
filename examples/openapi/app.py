"""OpenAPI example — demonstrates how to export an OpenAPI 3.0 specification
from a Microdot application.

Run with::

    python examples/openapi/app.py

Then visit:

    http://localhost:5000/openapi.json  — raw OpenAPI JSON document
    http://localhost:5000/docs          — Swagger UI rendering the spec
"""

from microdot import Microdot
from microdot.openapi import get_openapi, get_openapi_json, openapi

app = Microdot()

# ---------------------------------------------------------------------------
# Sample in-memory data store
# ---------------------------------------------------------------------------
ITEMS = {
    1: {'id': 1, 'name': 'Widget'},
    2: {'id': 2, 'name': 'Gadget'},
}
_next_id = 3


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get('/items')
@openapi(
    summary='List all items',
    responses={200: {'description': 'A list of items'}},
)
def list_items(req):
    """Return every item in the store."""
    return list(ITEMS.values())


@app.get('/items/<int:id>')
@openapi(
    summary='Get an item by ID',
    responses={
        200: {'description': 'The requested item'},
        404: {'description': 'Item not found'},
    },
)
def get_item(req, id):
    """Return a single item identified by its *id*."""
    item = ITEMS.get(id)
    if item is None:
        return {'error': 'not found'}, 404
    return item


@app.post('/items')
@openapi(
    summary='Create a new item',
    responses={201: {'description': 'The newly created item'}},
)
def create_item(req):
    """Create a new item. Expects a JSON body with a ``name`` field."""
    global _next_id
    data = req.json or {}
    item = {'id': _next_id, 'name': data.get('name', '')}
    ITEMS[_next_id] = item
    _next_id += 1
    return item, 201


@app.delete('/items/<int:id>')
@openapi(
    summary='Delete an item',
    responses={
        204: {'description': 'Item deleted'},
        404: {'description': 'Item not found'},
    },
)
def delete_item(req, id):
    """Delete the item with the given *id*."""
    if id not in ITEMS:
        return {'error': 'not found'}, 404
    del ITEMS[id]
    return '', 204


# ---------------------------------------------------------------------------
# OpenAPI endpoints
# ---------------------------------------------------------------------------

@app.get('/openapi.json')
def openapi_spec(req):
    """Serve the OpenAPI specification as JSON."""
    return get_openapi_json(
        app,
        title='Items API',
        version='1.0.0',
        description='A simple CRUD API for items, powered by Microdot.',
    ), 200, {'Content-Type': 'application/json'}


@app.get('/docs')
def docs(req):
    """Serve a minimal Swagger UI page that loads the spec from
    ``/openapi.json``."""
    return '''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Items API — Swagger UI</title>
  <link rel="stylesheet"
        href="https://unpkg.com/swagger-ui-dist/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({url: "/openapi.json", dom_id: "#swagger-ui"});
  </script>
</body>
</html>''', 200, {'Content-Type': 'text/html'}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)

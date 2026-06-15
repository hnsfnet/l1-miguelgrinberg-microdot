"""
openapi
-------

The ``openapi`` module provides utilities for introspecting Microdot
application routes and exporting them as an OpenAPI 3.0 specification.
"""

try:
    import orjson as json  # type: ignore[import-not-found]

    def _dumps(obj):
        return json.dumps(obj).decode()
except ImportError:
    import json

    def _dumps(obj):
        return json.dumps(obj, indent=2)


# Maps Microdot URL segment types to OpenAPI schema types.
_SEGMENT_TYPE_MAP = {
    'string': {'type': 'string'},
    'int': {'type': 'integer'},
    'path': {'type': 'string'},
}


def _url_pattern_to_openapi(url_pattern_obj):
    """Convert a :class:`~microdot.URLPattern` instance into an OpenAPI-style
    path string (e.g. ``/users/<int:id>`` becomes ``/users/{id}``) and return
    a list of parameter descriptors.

    :param url_pattern_obj: A :class:`~microdot.URLPattern` instance.
    :returns: A tuple ``(openapi_path, parameters)`` where ``parameters`` is a
        list of OpenAPI parameter dicts.
    """
    # Ensure segments are populated.
    if url_pattern_obj.segments is None or url_pattern_obj.segments == []:
        url_pattern_obj.compile()

    path_parts = []
    parameters = []

    raw = url_pattern_obj.url_pattern.lstrip('/')
    if not raw:
        return '/', parameters

    for segment in raw.split('/'):
        if segment and segment[0] == '<' and segment[-1] == '>':
            inner = segment[1:-1]
            if ':' in inner:
                type_, name = inner.rsplit(':', 1)
            else:
                type_ = 'string'
                name = inner

            # Strip ``re:`` prefix — for regex types we just expose the name.
            if type_.startswith('re:'):
                schema = {'type': 'string'}
            else:
                schema = dict(_SEGMENT_TYPE_MAP.get(type_, {'type': 'string'}))

            path_parts.append('{' + name + '}')
            parameters.append({
                'name': name,
                'in': 'path',
                'required': True,
                'schema': schema,
            })
        else:
            path_parts.append(segment)

    return '/' + '/'.join(path_parts), parameters


def get_routes(app):
    """Return a list of dictionaries describing every route registered on
    ``app``.

    Each dictionary contains the following keys:

    - ``methods``: a sorted list of HTTP methods handled by the route.
    - ``path``: the original URL pattern string as given to
      :meth:`~microdot.Microdot.route`.
    - ``openapi_path``: the URL pattern converted to OpenAPI path syntax
      (``<name>`` replaced with ``{name}``).
    - ``parameters``: a list of OpenAPI path-parameter descriptors for
      dynamic segments.
    - ``endpoint``: the name of the handler function.
    - ``summary``: a short human-readable summary. Taken from the handler's
      ``openapi`` attribute (``summary`` key) if present, otherwise the first
      line of the handler's docstring, otherwise the handler's function name.
    - ``description``: a longer description. Taken from the handler's
      ``openapi`` attribute (``description`` key) if present, otherwise the
      remainder of the docstring after the first line. Empty string when
      unavailable.
    - ``responses``: a dictionary of response status-code / description
      pairs. Taken from the handler's ``openapi`` attribute (``responses``
      key) if present, otherwise a sensible default.

    :param app: A :class:`~microdot.Microdot` application instance.
    :returns: A list of route description dictionaries.
    """
    routes = []
    for methods, pattern, handler, _prefix, _subapp in app.url_map:
        openapi_path, parameters = _url_pattern_to_openapi(pattern)

        # Gather optional metadata attached to the handler by @openapi().
        meta = getattr(handler, 'openapi', {}) or {}

        # Derive summary.
        summary = meta.get('summary')
        description = meta.get('description', '')
        doc = (handler.__doc__ or '').strip()
        if summary is None:
            if doc:
                lines = doc.split('\n', 1)
                summary = lines[0].strip()
                description = description or (
                    lines[1].strip() if len(lines) > 1 else '')
            else:
                summary = handler.__name__

        # Derive responses.
        responses = meta.get('responses')
        if responses is None:
            responses = {}
            for method in methods:
                if method == 'POST':
                    responses.setdefault('201', {'description': 'Created'})
                elif method == 'DELETE':
                    responses.setdefault('204',
                                         {'description': 'No content'})
                else:
                    responses.setdefault('200', {'description': 'OK'})
        else:
            # Normalize keys to strings for consistency.
            responses = {str(k): v for k, v in responses.items()}

        routes.append({
            'methods': sorted(methods),
            'path': pattern.url_pattern,
            'openapi_path': openapi_path,
            'parameters': parameters,
            'endpoint': handler.__name__,
            'summary': summary,
            'description': description,
            'responses': responses,
        })
    return routes


def get_openapi(app, title='Microdot App', version='1.0.0',
                description='', openapi_version='3.0.3'):
    """Build and return an OpenAPI 3.0 specification as a Python dictionary.

    :param app: A :class:`~microdot.Microdot` application instance.
    :param title: The API title.
    :param version: The API version string.
    :param description: An optional top-level description.
    :param openapi_version: The OpenAPI specification version. Defaults to
        ``3.0.3``.
    :returns: A dictionary representing the OpenAPI specification.
    """
    paths = {}
    for route in get_routes(app):
        path_item = paths.setdefault(route['openapi_path'], {})
        operation = {
            'summary': route['summary'],
            'operationId': route['endpoint'],
            'responses': {
                str(code): info
                for code, info in route['responses'].items()
            },
        }
        if route['description']:
            operation['description'] = route['description']
        if route['parameters']:
            operation['parameters'] = route['parameters']

        for method in route['methods']:
            path_item[method.lower()] = operation

    spec = {
        'openapi': openapi_version,
        'info': {
            'title': title,
            'version': version,
        },
        'paths': paths,
    }
    if description:
        spec['info']['description'] = description
    return spec


def get_openapi_json(app, title='Microdot App', version='1.0.0',
                     description='', openapi_version='3.0.3'):
    """Return the OpenAPI 3.0 specification as a JSON string.

    Parameters are identical to :func:`get_openapi`.
    """
    return _dumps(get_openapi(
        app, title=title, version=version,
        description=description, openapi_version=openapi_version))


def openapi(summary=None, description=None, responses=None):
    """Decorator to attach OpenAPI metadata to a route handler.

    The metadata is used by :func:`get_routes` and :func:`get_openapi` when
    building the OpenAPI specification. Any parameters left as ``None`` fall
    back to their default derivation strategy.

    :param summary: A short summary of the operation.
    :param description: A longer description of the operation.
    :param responses: A dictionary mapping HTTP status codes (as strings or
        integers) to response descriptor dicts.

    Example::

        from microdot import Microdot
        from microdot.openapi import openapi, get_openapi

        app = Microdot()

        @app.get('/users/<int:id>')
        @openapi(
            summary='Get a user by ID',
            responses={
                200: {'description': 'A user object'},
                404: {'description': 'User not found'},
            },
        )
        def get_user(request, id):
            ...
    """
    def decorated(f):
        f.openapi = {
            'summary': summary,
            'description': description,
            'responses': responses,
        }
        return f
    return decorated

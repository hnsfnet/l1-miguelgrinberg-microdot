"""
microdot.openapi
----------------

This module provides route introspection and a minimal `OpenAPI
<https://www.openapis.org/>`_ document generator for Microdot applications.

The :func:`describe_routes` function returns the routes that are registered
with an application as a list of plain dictionaries, without requiring the
caller to inspect Microdot's internal objects. The :func:`generate_openapi`
and :func:`generate_openapi_json` functions build on top of it to export an
OpenAPI 3 document, either as a Python dictionary or as a JSON string.
"""
try:
    import json
except ImportError:  # pragma: no cover
    import ujson as json  # type: ignore[import-not-found, no-redef]

#: The OpenAPI version that generated documents declare by default.
DEFAULT_OPENAPI_VERSION = '3.1.0'

#: The responses object used for operations that do not declare their own
#: responses through the :func:`openapi` decorator. Applications are free to
#: replace this object to change the default for the whole project.
DEFAULT_RESPONSES = {'200': {'description': 'Successful response'}}

# A mapping from Microdot URL segment types to OpenAPI schema objects. Types
# that are not listed here (including custom types registered with
# ``URLPattern.register_type`` and ``re:`` regular expression types) default to
# a plain string schema.
_TYPE_SCHEMAS = {
    'string': {'type': 'string'},
    'int': {'type': 'integer'},
    'path': {'type': 'string'},
}


def _parse_pattern(url_pattern):
    """Parse a Microdot URL pattern.

    Returns a tuple with the equivalent OpenAPI path template (using
    ``{name}`` placeholders for dynamic segments) and a list of path parameter
    descriptors. The pattern string is parsed directly so that this function
    has no side effects on the ``URLPattern`` object.
    """
    path_segments = []
    parameters = []
    for segment in url_pattern.lstrip('/').split('/'):
        if segment and segment[0] == '<':
            inner = segment[1:]
            if inner.endswith('>'):
                inner = inner[:-1]
            if ':' in inner:
                type_, name = inner.rsplit(':', 1)
            else:
                type_, name = 'string', inner
            path_segments.append('{' + name + '}')
            parameters.append({
                'name': name,
                'type': type_,
                'in': 'path',
                'required': True,
            })
        else:
            path_segments.append(segment)
    return '/' + '/'.join(path_segments), parameters


def _type_schema(type_):
    """Return the OpenAPI schema object for a Microdot segment type."""
    if type_.startswith('re:'):
        return {'type': 'string', 'pattern': type_[3:]}
    return dict(_TYPE_SCHEMAS.get(type_, {'type': 'string'}))


def _doc(handler):
    """Return the (summary, description) pair derived from a docstring.

    The summary is the first non-empty line of the handler's docstring. The
    description is the full, stripped docstring. Both values are ``None`` when
    the handler has no docstring.
    """
    doc = getattr(handler, '__doc__', None)
    if not doc:
        return None, None
    doc = doc.strip()
    if not doc:
        return None, None
    summary = doc.split('\n', 1)[0].strip()
    return summary, doc


def _operation_id(handler, method, seen):
    """Return a unique ``operationId`` for a handler/method combination."""
    base = getattr(handler, '__name__', None) or 'operation'
    candidate = base
    if candidate in seen:
        candidate = '{}_{}'.format(base, method.lower())
    suffix = 2
    while candidate in seen:
        candidate = '{}_{}_{}'.format(base, method.lower(), suffix)
        suffix += 1
    seen.add(candidate)
    return candidate


def _parameter_object(parameter):
    """Convert a path parameter descriptor to an OpenAPI parameter object."""
    return {
        'name': parameter['name'],
        'in': parameter['in'],
        'required': parameter['required'],
        'schema': _type_schema(parameter['type']),
    }


def describe_routes(app):
    """Return a readable description of the routes registered with an app.

    :param app: The :class:`Microdot <microdot.Microdot>` application to
                inspect. Sub-applications mounted with
                :meth:`mount() <microdot.Microdot.mount>` are included, as
                Microdot flattens them into the parent's route table.

    The return value is a list of dictionaries, one per registered route, in
    registration order. Each dictionary has the following keys:

    - ``path``: the original Microdot URL pattern, for example
      ``/users/<int:id>``.
    - ``openapi_path``: the same path using OpenAPI placeholders, for example
      ``/users/{id}``.
    - ``methods``: the sorted list of HTTP methods handled by the route.
    - ``parameters``: a list of dynamic path parameters. Each parameter has a
      ``name``, the Microdot ``type`` (``string``, ``int``, ``path``, a custom
      type or a ``re:`` regular expression type), the ``in`` location (always
      ``path``) and a ``required`` flag (always ``True``).
    - ``handler``: the name of the handler function, when available.
    - ``summary`` and ``description``: extracted from the handler's docstring,
      or ``None`` if it has none.

    Example::

        from microdot import Microdot
        from microdot.openapi import describe_routes

        app = Microdot()

        @app.get('/users/<int:id>')
        def get_user(request, id):
            \"\"\"Return a single user.\"\"\"
            ...

        describe_routes(app)
        # [{'path': '/users/<int:id>',
        #   'openapi_path': '/users/{id}',
        #   'methods': ['GET'],
        #   'parameters': [{'name': 'id', 'type': 'int',
        #                   'in': 'path', 'required': True}],
        #   'handler': 'get_user',
        #   'summary': 'Return a single user.',
        #   'description': 'Return a single user.'}]
    """
    routes = []
    for methods, pattern, handler, _url_prefix, _subapp in app.url_map:
        openapi_path, parameters = _parse_pattern(pattern.url_pattern)
        summary, description = _doc(handler)
        routes.append({
            'path': pattern.url_pattern,
            'openapi_path': openapi_path,
            'methods': sorted(methods),
            'parameters': parameters,
            'handler': getattr(handler, '__name__', None),
            'summary': summary,
            'description': description,
        })
    return routes


def _build_operation(handler, method, parameters, meta, seen):
    """Build a single OpenAPI operation object for a handler."""
    summary, description = _doc(handler)
    summary = meta.get('summary', summary)
    description = meta.get('description', description)

    operation = {}
    if summary:
        operation['summary'] = summary
    if description and description != summary:
        operation['description'] = description
    if 'tags' in meta:
        operation['tags'] = meta['tags']
    operation['operationId'] = meta.get('operationId') or \
        _operation_id(handler, method, seen)

    op_parameters = meta.get('parameters')
    if op_parameters is None:
        op_parameters = [_parameter_object(p) for p in parameters]
    if op_parameters:
        operation['parameters'] = op_parameters

    if 'requestBody' in meta:
        operation['requestBody'] = meta['requestBody']
    operation['responses'] = meta.get('responses') or \
        dict(DEFAULT_RESPONSES)
    return operation


def generate_openapi(app, title='Microdot API', version='1.0.0',
                     description=None, servers=None,
                     openapi_version=DEFAULT_OPENAPI_VERSION):
    """Generate an OpenAPI 3 document for an application.

    :param app: The :class:`Microdot <microdot.Microdot>` application to
                document.
    :param title: The title of the API, used in the ``info`` section.
    :param version: The version of the API, used in the ``info`` section.
    :param description: An optional description for the ``info`` section.
    :param servers: An optional list of OpenAPI server objects.
    :param openapi_version: The OpenAPI specification version to declare. The
                            default is ``3.1.0``.

    The document is returned as a Python dictionary, which can be served
    directly from a route, written to a file, or converted to JSON with
    :func:`generate_openapi_json`.

    Routes are grouped by path, and each HTTP method becomes an operation
    under its path. Dynamic path segments are represented as path parameters.
    Handlers that do not provide explicit metadata (through the
    :func:`openapi` decorator) fall back to sensible defaults: the docstring is
    used for the summary and description, the function name is used for the
    ``operationId``, and a single ``200`` response is declared. Registering
    routes in the usual way is enough; no metadata is required.

    Example::

        from microdot import Microdot
        from microdot.openapi import generate_openapi

        app = Microdot()

        @app.get('/')
        def index(request):
            return 'Hello, world!'

        spec = generate_openapi(app, title='Hello API', version='1.0.0')
    """
    paths = {}
    seen_operation_ids = set()
    for methods, pattern, handler, _url_prefix, _subapp in app.url_map:
        openapi_path, parameters = _parse_pattern(pattern.url_pattern)
        meta = getattr(handler, '_openapi', None) or {}
        path_item = paths.setdefault(openapi_path, {})
        for method in methods:
            path_item[method.lower()] = _build_operation(
                handler, method, parameters, meta, seen_operation_ids)

    info = {'title': title, 'version': version}
    if description:
        info['description'] = description
    spec = {
        'openapi': openapi_version,
        'info': info,
        'paths': paths,
    }
    if servers:
        spec['servers'] = servers
    return spec


def generate_openapi_json(app, indent=2, **kwargs):
    """Generate an OpenAPI 3 document for an application as a JSON string.

    :param app: The :class:`Microdot <microdot.Microdot>` application to
                document.
    :param indent: The indentation to use when formatting the JSON, or
                   ``None`` for compact output. Indentation is ignored on
                   interpreters whose ``json`` module does not support it.
    :param kwargs: Any additional keyword arguments are passed through to
                   :func:`generate_openapi`.

    This is a convenience wrapper that calls :func:`generate_openapi` and
    serializes the result with the ``json`` module, which makes it easy to
    write the document to a file or return it from a route.

    Example::

        with open('openapi.json', 'wt') as f:
            f.write(generate_openapi_json(app, title='My API'))
    """
    spec = generate_openapi(app, **kwargs)
    try:
        return json.dumps(spec, indent=indent)
    except TypeError:  # pragma: no cover
        # some MicroPython builds do not support the ``indent`` argument
        return json.dumps(spec)


def openapi(summary=None, description=None, responses=None, tags=None,
            operation_id=None, request_body=None, parameters=None):
    """Decorator that attaches OpenAPI metadata to a route handler.

    :param summary: A short summary of what the operation does.
    :param description: A longer description of the operation.
    :param responses: An OpenAPI responses object. When omitted,
                      :data:`DEFAULT_RESPONSES` is used.
    :param tags: A list of tags used to group the operation.
    :param operation_id: A unique identifier for the operation. When omitted,
                         it is derived from the handler's name.
    :param request_body: An OpenAPI request body object.
    :param parameters: An explicit list of OpenAPI parameter objects. When
                       omitted, path parameters are derived from the URL
                       pattern.

    This decorator only stores the given values on the handler in an
    ``_openapi`` attribute and returns the handler unchanged, so it does not
    interfere with how routes are registered. It can be placed above or below
    the route decorator.

    Example::

        @app.get('/users/<int:id>')
        @openapi(summary='Get a user',
                 responses={'200': {'description': 'The requested user'},
                            '404': {'description': 'User not found'}})
        def get_user(request, id):
            ...
    """
    def decorator(f):
        meta = dict(getattr(f, '_openapi', None) or {})
        if summary is not None:
            meta['summary'] = summary
        if description is not None:
            meta['description'] = description
        if responses is not None:
            meta['responses'] = responses
        if tags is not None:
            meta['tags'] = tags
        if operation_id is not None:
            meta['operationId'] = operation_id
        if request_body is not None:
            meta['requestBody'] = request_body
        if parameters is not None:
            meta['parameters'] = parameters
        f._openapi = meta
        return f
    return decorator

OpenAPI and Route Introspection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :align: left

   * - Compatibility
     - | CPython & MicroPython

   * - Required Microdot source files
     - | `openapi.py <https://github.com/miguelgrinberg/microdot/tree/main/src/microdot/openapi.py>`_

   * - Required external dependencies
     - | None

   * - Examples
     - | `app.py <https://github.com/miguelgrinberg/microdot/blob/main/examples/openapi/app.py>`_

The OpenAPI extension makes it possible to inspect the routes that are
registered with an application and to export a minimal `OpenAPI
<https://www.openapis.org/>`_ document describing them.

Inspecting routes
^^^^^^^^^^^^^^^^^

The :func:`describe_routes <microdot.openapi.describe_routes>` function returns
the registered routes as a list of plain dictionaries, so there is no need to
read Microdot's internal route table directly. Each entry includes the URL
pattern, the equivalent OpenAPI path, the HTTP methods, the dynamic path
parameters and any documentation extracted from the handler's docstring.

::

    from microdot import Microdot
    from microdot.openapi import describe_routes

    app = Microdot()

    @app.get('/users/<int:id>')
    def get_user(request, id):
        """Return a single user."""
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

Dynamic path segments such as ``<id>`` or ``<int:id>`` are preserved in the
``parameters`` list, including their Microdot type, so they are never silently
dropped.

Exporting an OpenAPI document
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The :func:`generate_openapi <microdot.openapi.generate_openapi>` function
returns an OpenAPI 3 document as a Python dictionary. The
:func:`generate_openapi_json <microdot.openapi.generate_openapi_json>` function
returns the same document serialized to a JSON string, which is convenient for
writing to a file or returning from a route.

::

    from microdot import Microdot
    from microdot.openapi import generate_openapi

    app = Microdot()

    @app.get('/')
    def index(request):
        """Get the home page."""
        return 'Hello, world!'

    @app.get('/openapi.json')
    def spec(request):
        return generate_openapi(app, title='My API', version='1.0.0')

Routes that do not provide explicit metadata still produce a valid document.
The handler's docstring is used for the operation's summary and description,
the function name is used as the ``operationId``, and a single ``200`` response
is declared by default. Registering routes in the usual way is all that is
required.

Adding metadata
^^^^^^^^^^^^^^^

When more detail is needed, the
:func:`openapi <microdot.openapi.openapi>` decorator can be used to attach a
summary, description, tags, responses, request body or explicit parameters to a
handler. The decorator does not change how the route is registered, so it can
be added above or below the route decorator.

::

    from microdot.openapi import openapi

    @app.get('/users/<int:id>')
    @openapi(summary='Get a user',
             responses={'200': {'description': 'The requested user'},
                        '404': {'description': 'User not found'}})
    def get_user(request, id):
        ...

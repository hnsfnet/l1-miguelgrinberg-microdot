This directory contains an example that shows how to introspect an
application's routes and export an OpenAPI document with the
`microdot.openapi` module.

Run the example with `python app.py`. It prints a summary of the registered
routes on startup and serves the generated OpenAPI document at
`http://localhost:5000/openapi.json`.

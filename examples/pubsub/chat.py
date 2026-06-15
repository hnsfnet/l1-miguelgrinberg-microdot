import asyncio
from microdot import Microdot, send_file
from microdot.sse import with_sse
from microdot.websocket import with_websocket
from microdot.pubsub import PubSub

app = Microdot()

# A single pub/sub broker shared by every connection. Both the SSE and the
# WebSocket endpoints below subscribe to the same channel, so a message
# published from any client is broadcast to all of them regardless of the
# transport they are using.
pubsub = PubSub()

CHANNEL = 'chat'


@app.route('/')
async def index(request):
    return send_file('index.html')


@app.route('/publish', methods=['POST'])
async def publish(request):
    # publish a message received as a form field, e.g.:
    #   curl -d "message=hello" http://localhost:5000/publish
    message = (request.form or {}).get('message', '')
    subscribers = await pubsub.publish(CHANNEL, message)
    return {'delivered_to': subscribers}


@app.route('/events')
@with_sse
async def events(request, sse):
    # forward every message published to the channel to this SSE client
    await pubsub.stream(sse, CHANNEL)


@app.route('/ws')
@with_websocket
async def ws(request, ws):
    # send messages published to the channel to the client...
    async def sender():
        await pubsub.stream(ws, CHANNEL)

    sender_task = asyncio.create_task(sender())
    try:
        # ...and publish to the channel whatever the client sends
        while True:
            message = await ws.receive()
            await pubsub.publish(CHANNEL, message)
    finally:
        sender_task.cancel()


if __name__ == '__main__':
    app.run(debug=True)

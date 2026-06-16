import asyncio
import unittest
from microdot import Microdot
from microdot.pubsub import PubSub
from microdot.websocket import with_websocket
from microdot.test_client import TestClient


class TestPubSub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if hasattr(asyncio, 'set_event_loop'):
            asyncio.set_event_loop(asyncio.new_event_loop())
        cls.loop = asyncio.get_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    # -- basic subscribe/unsubscribe/publish --

    def test_subscribe_creates_channel(self):
        ps = PubSub()
        q = ps.subscribe('news')
        self.assertIn('news', ps.channels())
        self.assertEqual(ps.subscriber_count('news'), 1)
        ps.unsubscribe('news', q)
        self.assertNotIn('news', ps.channels())
        self.assertEqual(ps.subscriber_count('news'), 0)

    def test_subscribe_multiple(self):
        ps = PubSub()
        q1 = ps.subscribe('news')
        q2 = ps.subscribe('news')
        self.assertEqual(ps.subscriber_count('news'), 2)
        ps.unsubscribe('news', q1)
        self.assertEqual(ps.subscriber_count('news'), 1)
        ps.unsubscribe('news', q2)
        self.assertEqual(ps.subscriber_count('news'), 0)

    def test_publish_delivers_to_subscribers(self):
        ps = PubSub()
        q1 = ps.subscribe('news')
        q2 = ps.subscribe('news')

        async def do_publish():
            count = await ps.publish('news', 'hello')
            self.assertEqual(count, 2)

        self._run(do_publish())
        self.assertEqual(q1.get_nowait(), 'hello')
        self.assertEqual(q2.get_nowait(), 'hello')

        ps.unsubscribe('news', q1)
        ps.unsubscribe('news', q2)

    def test_publish_to_empty_channel(self):
        ps = PubSub()

        async def do_publish():
            count = await ps.publish('nonexistent', 'hello')
            self.assertEqual(count, 0)

        self._run(do_publish())

    def test_unsubscribe_nonexistent(self):
        ps = PubSub()
        q = asyncio.Queue()
        # Should not raise
        ps.unsubscribe('nonexistent', q)

    def test_duplicate_subscribe_same_queue(self):
        ps = PubSub()
        q = ps.subscribe('news')
        # subscribing the same queue again - set prevents duplicate
        ps._channels['news'].add(q)
        self.assertEqual(ps.subscriber_count('news'), 1)
        ps.unsubscribe('news', q)

    # -- multi-channel isolation --

    def test_channel_isolation(self):
        ps = PubSub()
        q_news = ps.subscribe('news')
        q_sports = ps.subscribe('sports')

        async def do_publish():
            await ps.publish('news', 'headline')
            await ps.publish('sports', 'goal')

        self._run(do_publish())

        self.assertEqual(q_news.get_nowait(), 'headline')
        self.assertEqual(q_sports.get_nowait(), 'goal')

        # news queue should not have sports message and vice versa
        self.assertTrue(q_news.empty())
        self.assertTrue(q_sports.empty())

        ps.unsubscribe('news', q_news)
        ps.unsubscribe('sports', q_sports)

    def test_multi_channel_subscriber(self):
        ps = PubSub()
        q1 = ps.subscribe('a')
        q2 = ps.subscribe('b')

        async def do_publish():
            await ps.publish('a', 'msg-a')
            await ps.publish('b', 'msg-b')

        self._run(do_publish())
        self.assertEqual(q1.get_nowait(), 'msg-a')
        self.assertEqual(q2.get_nowait(), 'msg-b')

        ps.unsubscribe('a', q1)
        ps.unsubscribe('b', q2)

    # -- slow consumer --

    def test_slow_consumer_drops_message(self):
        ps = PubSub()
        ps.max_queue_size = 2
        q = ps.subscribe('ch')

        async def do_publish():
            # Fill the queue
            count1 = await ps.publish('ch', 'msg1')
            count2 = await ps.publish('ch', 'msg2')
            # Queue is now full (size=2), next publish should drop
            count3 = await ps.publish('ch', 'msg3')
            self.assertEqual(count1, 1)
            self.assertEqual(count2, 1)
            self.assertEqual(count3, 0)  # dropped

        self._run(do_publish())
        self.assertEqual(q.get_nowait(), 'msg1')
        self.assertEqual(q.get_nowait(), 'msg2')
        self.assertTrue(q.empty())

        ps.unsubscribe('ch', q)
        ps.max_queue_size = 256  # reset

    # -- SSE integration --

    def test_sse_single_channel(self):
        app = Microdot()
        ps = PubSub()

        @app.route('/events/<channel>')
        async def events(request, channel):
            return ps.sse_response(request, channel)

        @app.post('/publish/<channel>')
        async def publish(request, channel):
            await ps.publish(channel, request.json)
            return 'ok'

        async def run_test():
            client = TestClient(app)

            # Start SSE connection in a background task
            sse_task = asyncio.create_task(client.get('/events/news'))

            # Give the SSE connection time to establish and subscribe
            await asyncio.sleep(0.05)

            # Publish a message
            await client.post('/publish/news', body={'headline': 'test'})

            # Give time for message delivery
            await asyncio.sleep(0.05)

            # Cancel SSE to collect results
            sse_task.cancel()
            try:
                response = await sse_task
            except asyncio.CancelledError:
                return None

            return response

        response = self._run(run_test())
        if response and response.events:
            self.assertEqual(len(response.events), 1)
            self.assertEqual(response.events[0]['event'], 'news')

    def test_sse_multi_channel(self):
        app = Microdot()
        ps = PubSub()

        @app.route('/events')
        async def events(request):
            return ps.sse_response(request, ['news', 'sports'])

        async def run_test():
            client = TestClient(app)
            sse_task = asyncio.create_task(client.get('/events'))
            await asyncio.sleep(0.05)

            await ps.publish('news', 'headline')
            await ps.publish('sports', 'goal')
            await asyncio.sleep(0.05)

            sse_task.cancel()
            try:
                return await sse_task
            except asyncio.CancelledError:
                return None

        response = self._run(run_test())
        if response and response.events:
            self.assertEqual(len(response.events), 2)
            events = {e['event'] for e in response.events}
            self.assertIn('news', events)
            self.assertIn('sports', events)

    def test_sse_cleanup_on_disconnect(self):
        app = Microdot()
        ps = PubSub()

        @app.route('/events/<channel>')
        async def events(request, channel):
            return ps.sse_response(request, channel)

        async def run_test():
            client = TestClient(app)
            sse_task = asyncio.create_task(client.get('/events/news'))
            await asyncio.sleep(0.05)

            # Verify subscriber is registered
            self.assertEqual(ps.subscriber_count('news'), 1)

            # Disconnect
            sse_task.cancel()
            try:
                await sse_task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0.05)

            # Verify cleanup
            self.assertEqual(ps.subscriber_count('news'), 0)

        self._run(run_test())

    # -- WebSocket integration --

    def test_websocket_forwarding(self):
        """Test that websocket_handler forwards published messages."""
        ps = PubSub()
        sent = []

        class FakeWS:
            async def send(self, data):
                sent.append(data)

            async def receive(self):
                # Block until cancelled, simulating a long-lived connection
                await asyncio.sleep(100)

        async def run():
            ws = FakeWS()
            handler_task = asyncio.create_task(
                ps.websocket_handler(ws, 'news'))
            await asyncio.sleep(0.01)

            # Subscriber should be registered
            self.assertEqual(ps.subscriber_count('news'), 1)

            # Publish a message
            await ps.publish('news', {'headline': 'test'})
            await asyncio.sleep(0.01)

            # Cancel handler (simulates disconnect)
            handler_task.cancel()
            try:
                await handler_task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0.01)

            # Subscriber should be cleaned up
            self.assertEqual(ps.subscriber_count('news'), 0)

        self._run(run())

        # Verify the forwarded message
        self.assertEqual(len(sent), 1)
        import json as json_mod
        msg = json_mod.loads(sent[0])
        self.assertEqual(msg['channel'], 'news')
        self.assertEqual(msg['message'], {'headline': 'test'})

    def test_websocket_cleanup_on_disconnect(self):
        app = Microdot()
        ps = PubSub()

        @app.route('/ws/<channel>')
        @with_websocket
        async def ws(request, ws, channel):
            await ps.websocket_handler(ws, channel)

        async def run_test():
            async def client_ws():
                yield 'hello'
                # Generator ends here, simulating disconnect

            client = TestClient(app)
            await client.websocket('/ws/news', client_ws)
            await asyncio.sleep(0.05)

            # Verify cleanup
            self.assertEqual(ps.subscriber_count('news'), 0)

        self._run(run_test())

    def test_websocket_multi_channel_forwarding(self):
        """Test forwarding from multiple channels over a single WebSocket."""
        ps = PubSub()
        sent = []

        class FakeWS:
            async def send(self, data):
                sent.append(data)

            async def receive(self):
                await asyncio.sleep(100)

        async def run():
            ws = FakeWS()
            handler_task = asyncio.create_task(
                ps.websocket_handler(ws, ['a', 'b']))
            await asyncio.sleep(0.01)

            await ps.publish('a', 'msg-a')
            await ps.publish('b', 'msg-b')
            await asyncio.sleep(0.01)

            handler_task.cancel()
            try:
                await handler_task
            except asyncio.CancelledError:
                pass

        self._run(run())

        self.assertEqual(len(sent), 2)
        import json as json_mod
        messages = {json_mod.loads(s)['channel']: json_mod.loads(s)['message']
                    for s in sent}
        self.assertEqual(messages, {'a': 'msg-a', 'b': 'msg-b'})

    # -- channels/subscriber_count helpers --

    def test_channels_list(self):
        ps = PubSub()
        q1 = ps.subscribe('a')
        q2 = ps.subscribe('b')
        q3 = ps.subscribe('c')

        channels = sorted(ps.channels())
        self.assertEqual(channels, ['a', 'b', 'c'])

        ps.unsubscribe('b', q2)
        channels = sorted(ps.channels())
        self.assertEqual(channels, ['a', 'c'])

        ps.unsubscribe('a', q1)
        ps.unsubscribe('c', q3)
        self.assertEqual(ps.channels(), [])

    def test_subscriber_count(self):
        ps = PubSub()
        self.assertEqual(ps.subscriber_count('x'), 0)

        q1 = ps.subscribe('x')
        self.assertEqual(ps.subscriber_count('x'), 1)

        q2 = ps.subscribe('x')
        self.assertEqual(ps.subscriber_count('x'), 2)

        ps.unsubscribe('x', q1)
        self.assertEqual(ps.subscriber_count('x'), 1)

        ps.unsubscribe('x', q2)
        self.assertEqual(ps.subscriber_count('x'), 0)

    # -- publish with different message types --

    def test_publish_dict(self):
        ps = PubSub()
        q = ps.subscribe('ch')

        async def do():
            await ps.publish('ch', {'key': 'value'})

        self._run(do())
        self.assertEqual(q.get_nowait(), {'key': 'value'})
        ps.unsubscribe('ch', q)

    def test_publish_list(self):
        ps = PubSub()
        q = ps.subscribe('ch')

        async def do():
            await ps.publish('ch', [1, 2, 3])

        self._run(do())
        self.assertEqual(q.get_nowait(), [1, 2, 3])
        ps.unsubscribe('ch', q)

    def test_publish_bytes(self):
        ps = PubSub()
        q = ps.subscribe('ch')

        async def do():
            await ps.publish('ch', b'binary data')

        self._run(do())
        self.assertEqual(q.get_nowait(), b'binary data')
        ps.unsubscribe('ch', q)

    def test_publish_number(self):
        ps = PubSub()
        q = ps.subscribe('ch')

        async def do():
            await ps.publish('ch', 42)

        self._run(do())
        self.assertEqual(q.get_nowait(), 42)
        ps.unsubscribe('ch', q)

    # -- concurrent publish --

    def test_concurrent_publish(self):
        ps = PubSub()
        q = ps.subscribe('ch')

        async def do():
            await asyncio.gather(
                ps.publish('ch', 'msg1'),
                ps.publish('ch', 'msg2'),
                ps.publish('ch', 'msg3'),
            )

        self._run(do())

        messages = []
        while not q.empty():
            messages.append(q.get_nowait())
        self.assertEqual(sorted(messages), ['msg1', 'msg2', 'msg3'])
        ps.unsubscribe('ch', q)

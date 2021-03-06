import asyncio
import random
import uuid
from unittest import TestCase, main

import requests
from urllib3 import Retry

from acapelladb import Session
from acapelladb.IndexField import IndexField, IndexFieldType, IndexFieldOrder
from acapelladb.PartitionIndex import QueryCondition
from acapelladb.utils.errors import CasError

USER = 'user'
PASSWORD = 'password'

session = Session(port=5678)

requests.post('http://localhost:5678/auth/signup', json={
    'username': USER,
    'password': PASSWORD,
    'email': 'test@test.ru'
})

loop = asyncio.get_event_loop()
loop.run_until_complete(session.login(USER, PASSWORD))


def async_test(f):
    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        future = coro(*args, **kwargs)
        loop.run_until_complete(future)
    return wrapper


def random_tree():
    c = random.randint(1, 3)
    return [USER] + [str(uuid.uuid4()) for _ in range(c)]


def random_partition():
    c = random.randint(1, 3)
    return [USER] + [str(uuid.uuid4()) for _ in range(c)]


def random_clustering():
    c = random.randint(1, 3)
    return [str(uuid.uuid4()) for _ in range(c)]


def random_value():
    return str(uuid.uuid4())


# Для тестов необходимы запущенные KV (127.0.0.1:10000), HTTP (127.0.0.1:12000) и AppServer (127.0.0.1:5678) ноды


class TestKvNonTx(TestCase):
    @async_test
    async def test_get(self):
        await session.get_entry(random_partition())

    @async_test
    async def test_set(self):
        await session.entry(random_partition()).set(random_value())

    @async_test
    async def test_set_none(self):
        await session.entry(random_partition()).set(None)

    @async_test
    async def test_return_set_value(self):
        key = random_partition()
        value = random_value()
        await session.entry(key).set(value)
        assert (await session.get_entry(key)).value == value

    @async_test
    async def test_cas_success(self):
        key = random_partition()
        value = random_value()
        await session.entry(key).cas(value)
        assert (await session.get_entry(key)).value == value

    @async_test
    async def test_cas_failed(self):
        key = random_partition()
        value = random_value()
        entry = await session.get_entry(key)
        with self.assertRaises(CasError):
            await entry.cas(value, entry.version + 1)

    @async_test
    async def test_get_version_returns_valid_version(self):
        key = random_partition()
        value = random_value()
        entry = session.entry(key)
        await entry.set(value)
        version = await session.get_version(key)
        assert entry.version == version


class TestKvClustering(TestCase):
    @async_test
    async def test_get(self):
        await session.get_entry(random_partition(), random_clustering())

    @async_test
    async def test_set(self):
        await session.entry(random_partition(), random_clustering()).set(random_value())

    @async_test
    async def test_set_none(self):
        await session.entry(random_partition(), random_clustering()).set(None)

    @async_test
    async def test_return_set_value(self):
        partition = random_partition()
        clustering = random_clustering()
        value = random_value()
        await session.entry(partition, clustering).set(value)
        assert (await session.get_entry(partition, clustering)).value == value

    @async_test
    async def test_cas_success(self):
        partition = random_partition()
        clustering = random_clustering()
        value = random_value()
        await session.entry(partition, clustering).cas(value)
        assert (await session.get_entry(partition, clustering)).value == value

    @async_test
    async def test_cas_failed(self):
        partition = random_partition()
        clustering = random_clustering()
        value = random_value()
        entry = await session.get_entry(partition, clustering)
        with self.assertRaises(CasError):
            await entry.cas(value, entry.version + 1)

    @async_test
    async def test_get_version_returns_valid_version(self):
        partition = random_partition()
        clustering = random_clustering()
        value = random_value()
        entry = session.entry(partition, clustering)
        await entry.set(value)
        version = await session.get_version(partition, clustering)
        assert entry.version == version

    @async_test
    async def test_range(self):
        partition = random_partition()
        a = ['aaa', 'aaa']
        b = ['bbb']
        c = ['ccc']

        await session.entry(partition, a).set('foo')
        await session.entry(partition, b).set('bar')
        await session.entry(partition, c).set('baz')

        result = await session.range(partition)
        assert [a, b, c] == [e.clustering for e in result]

        result = await session.range(partition, first=a)
        assert [b, c] == [e.clustering for e in result]

        result = await session.range(partition, last=b)
        assert [a, b] == [e.clustering for e in result]

        result = await session.range(partition, limit=2)
        assert [a, b] == [e.clustering for e in result]

    @async_test
    async def test_prefix(self):
        partition = random_partition()
        a = ['aaa', 'aaa', 'aaa']
        b = ['aaa', 'bbb', 'bbb']
        c = ['ccc', 'ccc']

        await session.entry(partition, a).set('foo')
        await session.entry(partition, b).set('bar')
        await session.entry(partition, c).set('baz')

        result = await session.range(partition, prefix=['aaa'])
        assert [a, b] == [e.clustering for e in result]

        result = await session.range(partition, prefix=['aaa', 'aaa'])
        assert [a] == [e.clustering for e in result]

        result = await session.range(partition, prefix=['ccc'])
        assert [c] == [e.clustering for e in result]


class TestKvTx(TestCase):
    @async_test
    async def test_create_tx(self):
        async with session.transaction():
            pass

    @async_test
    async def test_tx_rollback(self):
        async with session.transaction() as tx:
            await tx.rollback()

    @async_test
    async def test_old_value_if_rollback(self):
        key = random_partition()
        async with session.transaction() as tx:
            e = await tx.get_entry(key)
            value = e.value
            await e.set(random_value())
            await tx.rollback()

        async with session.transaction() as tx:
            e = await tx.get_entry(key)
            assert value == e.value

    @async_test
    async def test_rollback_if_error(self):
        key = random_partition()
        value = None
        try:
            async with session.transaction() as tx:
                e = await tx.get_entry(key)
                value = e.value
                await e.set(random_value())
                raise Exception()
        except Exception:
            pass

        async with session.transaction() as tx:
            e = await tx.get_entry(key)
            assert value == e.value

    @async_test
    async def test_see_set_in_other_tx(self):
        key = random_partition()
        value = random_value()

        async with session.transaction() as tx:
            await tx.entry(key).set(value)

        async with session.transaction() as tx:
            e = await tx.get_entry(key)
            assert value == e.value


class TestDtNonTx(TestCase):
    @async_test
    async def test_get(self):
        await session.tree(random_tree()).get_cursor(random_clustering())

    @async_test
    async def test_set(self):
        await session.tree(random_tree()).cursor(random_clustering()).set(random_value())

    @async_test
    async def test_return_set_value(self):
        tree = session.tree(random_tree())
        key = random_clustering()
        value = random_value()
        await tree.cursor(key).set(value)
        assert value == (await tree.get_cursor(key)).value

    @async_test
    async def test_next(self):
        tree = session.tree(random_tree())
        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        c = await tree.get_cursor(['A', 'A'])

        c = await c.next()
        assert c.key == ['A', 'B']
        assert c.value == 'bar'

        c = await c.next()
        assert c.key == ['B', 'A']
        assert c.value == 'baz'

        c = await c.next()
        assert c is None

    @async_test
    async def test_prev(self):
        tree = session.tree(random_tree())
        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        c = await tree.get_cursor(['B', 'A'])

        c = await c.prev()
        assert c.key == ['A', 'B']
        assert c.value == 'bar'

        c = await c.prev()
        assert c.key == ['A', 'A']
        assert c.value == 'foo'

        c = await c.prev()
        assert c is None


class TestDtTx(TestCase):
    @async_test
    async def test_see_set_in_other_tx(self):
        tree = session.tree(random_tree())

        async with session.transaction() as tx:
            await tree.cursor(['A'], tx).set('foo')
            await tree.cursor(['B'], tx).set('bar')

        async with session.transaction() as tx:
            assert (await tree.get_cursor(['A'], tx)).value == 'foo'
            assert (await tree.get_cursor(['B'], tx)).value == 'bar'

    @async_test
    async def test_old_value_if_rollback(self):
        tree = session.tree(random_tree())

        async with session.transaction() as tx:
            await tree.cursor(['A'], tx).set('foo')
            await tree.cursor(['B'], tx).set('bar')
            await tx.rollback()

        async with session.transaction() as tx:
            assert (await tree.get_cursor(['A'], tx)).value is None
            assert (await tree.get_cursor(['B'], tx)).value is None


class TestDtRange(TestCase):
    @async_test
    async def test_range_all_keys(self):
        tree = session.tree(random_tree())

        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        result = await tree.range()
        assert len(result) == 3
        assert result[0].key == ['A', 'A']
        assert result[0].value == 'foo'
        assert result[1].key == ['A', 'B']
        assert result[1].value == 'bar'
        assert result[2].key == ['B', 'A']
        assert result[2].value == 'baz'

    @async_test
    async def test_range_first(self):
        tree = session.tree(random_tree())

        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        result = await tree.range(first=['A', 'A'])
        assert len(result) == 2
        assert result[0].key == ['A', 'B']
        assert result[0].value == 'bar'
        assert result[1].key == ['B', 'A']
        assert result[1].value == 'baz'

    @async_test
    async def test_range_last(self):
        tree = session.tree(random_tree())

        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        result = await tree.range(last=['A', 'B'])
        assert len(result) == 2
        assert result[0].key == ['A', 'A']
        assert result[0].value == 'foo'
        assert result[1].key == ['A', 'B']
        assert result[1].value == 'bar'

    @async_test
    async def test_range_limit(self):
        tree = session.tree(random_tree())

        await tree.cursor(['A', 'A']).set('foo')
        await tree.cursor(['A', 'B']).set('bar')
        await tree.cursor(['B', 'A']).set('baz')

        result = await tree.range(limit=2)
        assert len(result) == 2
        assert result[0].key == ['A', 'A']
        assert result[0].value == 'foo'
        assert result[1].key == ['A', 'B']
        assert result[1].value == 'bar'


class TestKvBatch(TestCase):
    @async_test
    async def test_batch_set(self):
        batch = session.batch_manual()
        p1 = random_partition()
        p2 = random_partition()

        session.entry(p1, ['aaa']).set('111', batch=batch)
        session.entry(p1, ['bbb']).set('222', batch=batch)
        session.entry(p2, ['aaa']).set('333', batch=batch)
        session.entry(p2, ['bbb']).set('444', batch=batch)
        session.entry(p2, ['ccc']).set('555', batch=batch)

        await batch.send()

        assert '111' == (await session.get_entry(p1, ['aaa'])).value
        assert '222' == (await session.get_entry(p1, ['bbb'])).value
        assert '333' == (await session.get_entry(p2, ['aaa'])).value
        assert '444' == (await session.get_entry(p2, ['bbb'])).value
        assert '555' == (await session.get_entry(p2, ['ccc'])).value

    @async_test
    async def test_batch_set_awaitable(self):
        batch = session.batch_manual()
        p1 = random_partition()

        f = session.entry(p1, ['aaa']).set('111', batch=batch)
        await batch.send()

        asyncio.wait_for(1.0, f)

    @async_test
    async def test_batch_cas(self):
        batch = session.batch_manual()
        p1 = random_partition()

        session.entry(p1, ['aaa']).cas('111', 0, batch=batch)
        await batch.send()

        assert '111' == (await session.get_entry(p1, ['aaa'])).value


class IndexTest(TestCase):
    @async_test
    async def test_set_index(self):
        partition = random_partition()
        indexed = session.partition_index(partition)

        indexes = {
            1: [
                IndexField('foo', IndexFieldType.string, IndexFieldOrder.ascending),
                IndexField('bar', IndexFieldType.number, IndexFieldOrder.descending),
            ]
        }

        await indexed.set_index(1, indexes[1])
        result = await indexed.get_indexes()
        assert indexes == result

    @async_test
    async def test_get_indexes_values(self):
        partition = random_partition()
        indexed = session.partition_index(partition)

        indexes = {
            1: [
                IndexField('foo', IndexFieldType.string, IndexFieldOrder.ascending),
                IndexField('bar', IndexFieldType.number, IndexFieldOrder.descending),
            ],
            2: [
                IndexField('foo', IndexFieldType.string, IndexFieldOrder.ascending),
            ]
        }
        await indexed.set_index(1, indexes[1])
        await indexed.set_index(2, indexes[2])

        await (session.entry(partition, ['111']).set({'foo': 'aaa', 'bar': 123}, reindex=True))
        await (session.entry(partition, ['222']).set({'foo': 'aaa', 'bar': 456}, reindex=True))
        await (session.entry(partition, ['333']).set({'foo': 'aaa', 'bar': 789}, reindex=True))
        await (session.entry(partition, ['444']).set({'foo': 'bbb', 'bar': 777}, reindex=True))

        result = await indexed.query({'foo': QueryCondition(eq='aaa')})
        assert [['111'], ['222'], ['333']] == [e.clustering for e in result]

        result = await indexed.query({'foo': QueryCondition(eq='bbb')})
        assert [['444']] == [e.clustering for e in result]

        result = await indexed.query({'foo': QueryCondition(eq='aaa'), 'bar': QueryCondition(from_=456)})
        assert [['111'], ['222']] == [e.clustering for e in result]


if __name__ == '__main__':
    main()

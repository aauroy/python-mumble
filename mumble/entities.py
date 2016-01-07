import asyncio
import operator

from google.protobuf import descriptor


class Entity(object):
    FIELDS = {}
    BLOB_FIELDS = set()

    def __init__(self):
        self._futures = {}
        self._hashes = {}

        for k in self.FIELDS:
            setattr(self, k, None)

    def _future_for_field(self, name):
        return self._futures[name]

    def update_from_state(self, state):
        for k, f in self.FIELDS.items():
            if state.DESCRIPTOR.fields_by_name[f].label == \
                descriptor.FieldDescriptor.LABEL_REPEATED:
                v = list(getattr(state, f))
            elif state.HasField(f):
                v = getattr(state, f)
            else:
                continue

            setattr(self, k, v)

        for k in self.BLOB_FIELDS:
            if state.HasField(k + '_hash'):
                hash = getattr(state, k + '_hash')
                if self._hashes.get(k) != hash and k in self._futures:
                    self._futures[k].cancel()
                    del self._futures[k]
                self._hashes[k] = hash

            if k not in self._futures:
                self._futures[k] = asyncio.Future()

            if not self._futures[k].done():
                if state.HasField(k):
                    self._futures[k].set_result(getattr(state, k))
                elif k not in self._hashes:
                    self._futures[k].set_result(None)


class Channel(Entity):
    FIELDS = {
        'parent_id': 'parent',
        'link_ids': 'links',
        'name': 'name',
        'position': 'position',
    }

    BLOB_FIELDS = {
        'description'
    }

    def __init__(self, client, id):
        super().__init__()
        self.client = client
        self.id = id

    def get_parent(self):
        if self.parent_id is None:
            return None
        return self.client.channels[self.parent_id]

    def get_links(self):
        return [self.client.channels[link_id]
                for link_id in self.link_ids]

    def get_children(self):
        children = [channel for channel in self.client.channels.values()
                            if channel.parent_id == self.id]
        children.sort(key=operator.attrgetter('position'))
        return children

    def get_users(self):
        return [user for user in self.client.users.values()
                     if user.channel_id == self.id]

    async def get_description(self):
        fut = self._future_for_field('description')
        if not fut.done():
            self.client.request_blobs(description_for_channels=[self])
        return (await fut)


class User(Entity):
    FIELDS = {
        'user_id': 'user_id',
        'name': 'name',
        'channel_id': 'channel_id',
        'mute': 'mute',
        'deaf': 'deaf',
        'suppress': 'suppress',
        'self_mute': 'self_mute',
        'self_deaf': 'self_deaf',
        'hash': 'hash',
        'priority_speaker': 'priority_speaker',
        'recording': 'recording',
    }

    BLOB_FIELDS = {
        'comment',
        'texture'
    }

    def __init__(self, client, session):
        super().__init__()
        self.client = client
        self.session = session

    def get_channel(self):
        return self.client.channels[self.channel_id]

    async def get_comment(self):
        fut = self._future_for_field('comment')
        if not fut.done():
            self.client.request_blobs(comment_for_users=[self])
        return (await fut)

    async def get_texture(self):
        fut = self._future_for_field('texture')
        if not fut.done():
            self.client.request_blobs(texture_for_users=[self])
        return (await fut)

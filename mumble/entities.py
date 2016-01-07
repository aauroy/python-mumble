import operator

from google.protobuf import descriptor


class Entity(object):
    FIELDS = {}

    def __init__(self):
        for k in self.FIELDS:
            setattr(self, k, None)

    def update_from_state(self, message):
        for k, f in self.FIELDS.items():
            v = getattr(message, f)

            if message.DESCRIPTOR.fields_by_name[f].label == \
                descriptor.FieldDescriptor.LABEL_REPEATED:
                v = list(v)
            elif not message.HasField(v):
                continue

            setattr(self, k, v)


class Channel(Entity):
    FIELDS = {
        'parent_id': 'parent',
        'link_ids': 'links',
        'name': 'name',
        'description': 'description',
        'position': 'position',
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
        'comment_hash': 'comment_hash',
        'comment': 'comment',
        'texture_hash': 'texture_hash',
        'texture': 'texture',
        'priority_speaker': 'priority_speaker',
        'recording': 'recording',
    }

    def __init__(self, client, session):
        super().__init__()
        self.client = client
        self.session = session

    def get_channel(self):
        return self.client.channels[self.channel_id]

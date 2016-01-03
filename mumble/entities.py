import operator


class Channel(object):
    def __init__(self, store, id):
        self.store = store
        self.id = id

    def get_parent(self):
        if self.parent_id is None:
            return None
        return self.store.channels[self.parent_id]

    def get_links(self):
        return [self.store.channels[link_id]
                for link_id in self.link_ids]

    def get_children(self):
        children = [channel for channel in self.store.channels.values()
                            if channel.parent_id == self.id]
        children.sort(key=operator.attrgetter('position'))
        return children

    def get_users(self):
        return [user for user in self.store.users.values()
                     if user.channel_id == self.id]

    def update_from_state(self, message):
        self.parent_id = message.parent if message.HasField('parent') \
                                        else None
        self.link_ids = list(message.links)
        self.name = message.name
        self.description = message.description
        self.position = message.position


class User(object):
    def __init__(self, store, session):
        self.store = store
        self.session = session

    def update_from_state(self, message):
        self.user_id = message.user_id if message.HasField('user_id') else None
        self.name = message.name
        self.channel_id = message.channel_id
        self.mute = message.mute
        self.deaf = message.deaf
        self.suppress = message.suppress
        self.self_mute = message.self_mute
        self.self_deaf = message.self_deaf
        self.hash = message.hash

        self.comment_hash = message.comment_hash
        self.comment = message.comment

        self.texture_hash = message.texture_hash
        self.texture = message.texture

        self.priority_speaker = message.priority_speaker
        self.recording = message.recording

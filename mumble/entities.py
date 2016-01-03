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


class Store(object):
    def __init__(self):
        self.channels = {}
        self.channels_by_name = {}

        self.users = {}
        self.users_by_name = {}

    def add_channel(self, state):
        if state.channel_id not in self.channels:
            self.channels[state.channel_id] = Channel(self, state.channel_id)
        else:
            del self.channels_by_name[self.channels[state.channel_id].name]
        self.channels[state.channel_id].update_from_state(state)
        self.channels_by_name[self.channels[state.channel_id].name] = \
            self.channels[state.channel_id]
        return self.channels[state.channel_id]

    def remove_channel(self, id):
        channel = self.channels[id]
        del self.channels[id]
        del self.channels_by_name[channel.name]

    def add_user(self, state):
        if state.session not in self.users:
            self.users[state.session] = User(self, state.session)
        else:
            del self.users_by_name[self.users[state.session].name]
        self.users[state.session].update_from_state(state)
        self.users_by_name[self.users[state.session].name] = \
            self.users[state.session]
        return self.users[state.session]

    def remove_user(self, session):
        user = self.users[session]
        del self.users[session]
        del self.users_by_name[user.name]

    def get_root_channel(self):
        return self.channels[0]

import asyncio
import ssl

from . import entities
from . import protocol


class Client(object):
    MUMBLE_VERSION = (1, 2, 4)

    def __init__(self):
        self.channels = {}
        self.channels_by_name = {}

        self.users = {}
        self.users_by_name = {}

    async def connect(self, host, port, username, password=None, ssl_ctx=None):
        if ssl_ctx is None:
            ssl_ctx = ssl.create_default_context()

        self.loop = asyncio.get_event_loop()

        self.host = host
        self.port = port
        self.username = username

        self.control_protocol = protocol.ControlProtocol(self, self.username,
                                                         password)

        await self.loop.create_connection(lambda: self.control_protocol,
                                          self.host, self.port, ssl=ssl_ctx)

    @property
    def me(self):
        return self.users_by_name[self.username]

    def _add_channel(self, state):
        if state.channel_id not in self.channels:
            self.channels[state.channel_id] = entities.Channel(
                self, state.channel_id)
        else:
            # We need to delete the old channels_by_name mapping here.
            del self.channels_by_name[self.channels[state.channel_id].name]

        channel = self.channels[state.channel_id]
        channel.update_from_state(state)
        self.channels_by_name[channel.name] = channel
        return channel

    def _remove_channel(self, id):
        channel = self.channels[id]
        del self.channels[id]
        del self.channels_by_name[channel.name]

    def _add_user(self, state):
        if state.session not in self.users:
            self.users[state.session] = entities.User(self, state.session)
        else:
            # We need to delete the old users_by_name mapping here.
            del self.users_by_name[self.users[state.session].name]

        user = self.users[state.session]
        user.update_from_state(state)
        self.users_by_name[user.name] = user
        return user

    def _remove_user(self, session):
        user = self.users[session]
        del self.users[session]
        del self.users_by_name[user.name]

    def get_root_channel(self):
        return self.channels[0]

    def send_text_message(self, target, message, recursive=False):
        sessions = []
        channel_ids = []
        tree_ids = []

        if isinstance(target, entities.User):
            sessions.append(target.session)
        elif isinstance(target, entities.Channel):
            if recursive:
                tree_ids.append(target.id)
            else:
                channel_ids.append(target.id)

        self.control_protocol.send_text_message(
            self.me.session, message, sessions=sessions,
            channel_ids=channel_ids, tree_ids=tree_ids)

    def join_channel(self, channel):
        self.control_protocol.move_user(self.me.session, self.me.session,
                                        channel.id)

    def text_message_received(self, origin, target, message):
        # Override me!
        pass

    def connection_ready(self):
        # Override me!
        pass

    def mumble_channel_state_received(self, state):
        self._add_channel(state)

    def mumble_channel_remove_received(self, channel_id):
        self._remove_channel(channel_id)

    def mumble_user_state_received(self, state):
        self._add_user(state)

    def mumble_user_remove_received(self, session):
        self._remove_user(session)

    def mumble_text_message_received(self, actor, message, sessions,
                                     channel_ids):
        origin = self.users[actor]
        for session in sessions:
            self.text_message_received(origin, self.users[session], message)
        for channel_id in channel_ids:
            self.text_message_received(origin, self.channels[channel_id],
                                       message)

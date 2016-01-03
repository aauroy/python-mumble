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
        self.loop = asyncio.get_event_loop()

        self.host = host
        self.port = port
        self.username = username

        _, self.control_protocol = await self.loop.create_connection(
            lambda: protocol.ControlProtocol(self, self.username, password),
            self.host, self.port, ssl=ssl_ctx if ssl_ctx is not None
                                      else ssl.create_default_context())

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
        self.channels[state.channel_id].update_from_state(state)
        self.channels_by_name[state.name] = self.channels[state.channel_id]
        return self.channels[state.channel_id]

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
        self.users[state.session].update_from_state(state)
        self.users_by_name[state.name] = self.users[state.session]
        return self.users[state.session]

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
        self.control_protocol.join_channel(self.me.session, channel.id)

    def text_message_received(self, origin, target, message):
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

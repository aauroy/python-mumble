import asyncio
import ssl

from . import entities
from .protocols import control
from .protocols import voice


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

        self.control_protocol = control.Protocol(self, self.username, password)
        self.voice_protocol = voice.Protocol(self)

        await self.loop.create_connection(lambda: self.control_protocol,
                                          self.host, self.port, ssl=ssl_ctx)

    @property
    def me(self):
        return self.users_by_name[self.username]

    def _update_channel(self, state):
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

    def _update_user(self, state):
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

    def request_blobs(self, texture_for_users=None, comment_for_users=None,
                      description_for_channels=None):
        if texture_for_users is None:
            texture_for_users = []

        if comment_for_users is None:
            comment_for_users = []

        if description_for_channels is None:
            description_for_channels = []

        self.control_protocol.request_blobs(
            session_textures=[user.session for user in texture_for_users],
            session_comments=[user.session for user in comment_for_users],
            channel_descriptions=[channel.id
                                  for channel in description_for_channels])

    def user_move_channel(self, user, source, dest):
        # Override me!
        pass

    def user_connect(self, user):
        # Override me!
        pass

    def user_disconnect(self, user):
        # Override me!
        pass

    def text_message_received(self, origin, target, message):
        # Override me!
        pass

    def connection_ready(self):
        # Override me!
        pass

    def voice_received(self, user, target, pcm):
        # Override me!
        pass

    def voice_packet_received(self, session, target, pcm):
        self.voice_received(self.users[session], target, pcm)

    def control_connection_made(self):
        self.voice_protocol.connection_made(self.control_protocol.udp_tunnel)

    def control_codec_version_received(self, alpha, beta, prefer_alpha, opus):
        self.voice_protocol.setup_codecs(alpha, beta, prefer_alpha, opus)

    def control_crypt_setup_received(self, key, client_nonce, server_nonce):
        self.voice_protocol.setup_crypt(key, client_nonce, server_nonce)

    def control_udp_tunnel_received(self, packet):
        self.voice_protocol.plaintext_data_received(packet)

    def control_channel_state_received(self, state):
        self._update_channel(state)

    def control_channel_remove_received(self, channel_id):
        self._remove_channel(channel_id)

    def control_user_state_received(self, state):
        if state.session not in self.users:
            new_user = True
        else:
            new_user = False
            old_chan = self.users[state.session].channel_id
        self._update_user(state)
        user = self.users[state.session]
        if new_user:
            self.user_connect(user)
        else:
            print(self.channels[old_chan].name)
            print(self.channels[user.channel_id].name)
            self.user_move_channel(user, self.channels[old_chan], self.channels[user.channel_id])

    def control_user_remove_received(self, session):
        self.user_disconnect(self.users[session])
        self._remove_user(session)

    def control_text_message_received(self, actor, message, sessions,
                                      channel_ids):
        origin = self.users[actor]
        for session in sessions:
            self.text_message_received(origin, self.users[session], message)
        for channel_id in channel_ids:
            self.text_message_received(origin, self.channels[channel_id],
                                       message)

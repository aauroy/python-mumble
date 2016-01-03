import asyncio
import logging
import platform
import re
import ssl
import struct
import time

from . import entities
from . import Mumble_pb2


logger = logging.getLogger(__name__)


class MumbleProtocol(asyncio.Protocol):
    MUMBLE_VERSION = (1, 2, 4)

    PACKET_HEADER = struct.Struct('!HI')

    PACKET_TYPES = {
        0: Mumble_pb2.Version,
        1: Mumble_pb2.UDPTunnel,
        2: Mumble_pb2.Authenticate,
        3: Mumble_pb2.Ping,
        4: Mumble_pb2.Reject,
        5: Mumble_pb2.ServerSync,
        6: Mumble_pb2.ChannelRemove,
        7: Mumble_pb2.ChannelState,
        8: Mumble_pb2.UserRemove,
        9: Mumble_pb2.UserState,
        10: Mumble_pb2.BanList,
        11: Mumble_pb2.TextMessage,
        12: Mumble_pb2.PermissionDenied,
        13: Mumble_pb2.ACL,
        14: Mumble_pb2.QueryUsers,
        15: Mumble_pb2.CryptSetup,
        16: Mumble_pb2.ContextActionModify,
        17: Mumble_pb2.ContextAction,
        18: Mumble_pb2.UserList,
        19: Mumble_pb2.VoiceTarget,
        20: Mumble_pb2.PermissionQuery,
        21: Mumble_pb2.CodecVersion,
        22: Mumble_pb2.UserStats,
        23: Mumble_pb2.RequestBlob,
        24: Mumble_pb2.ServerConfig,
        25: Mumble_pb2.SuggestConfig,
    }

    PACKET_NUMBERS = {t: n for n, t in PACKET_TYPES.items()}

    @staticmethod
    def encode_version(major, minor, patch):
        return major << 16 | minor << 8 | patch

    def __init__(self, username, password=None):
        self.loop = asyncio.get_event_loop()

        self.username = username
        self.password = password
        self.buffer = bytearray()

        self._ping_handler = None

        self.users = {}
        self.user_name_id_map = {}

        self.store = entities.Store()

    @property
    def me(self):
        return self.store.users_by_name[self.username]

    def connection_made(self, transport):
        self.transport = transport
        self.send_version()
        self.authenticate(self.username, self.password)
        self.start_ping()

    def connection_lost(self, exc):
        if self._ping_handler is not None:
            self._ping_handler.cancel()

    def start_ping(self):
        self.send_message(Mumble_pb2.Ping(timestamp=int(time.time())))
        self._ping_handler = self.loop.call_later(20, self.start_ping)

    def send_version(self):
        self.send_message(Mumble_pb2.Version(
            version=self.encode_version(*self.MUMBLE_VERSION),
            release='.'.join(str(x) for x in self.MUMBLE_VERSION),
            os=platform.system(), os_version=platform.release()))

    def authenticate(self, username, password=None):
        auth_msg = Mumble_pb2.Authenticate(username=self.username)
        if self.password is not None:
            auth_msg.password = self.password
        self.send_message(auth_msg)

    def data_received(self, data):
        self.buffer.extend(data)
        self.process_buffer()

    def process_buffer(self):
        while True:
            try:
                type, length = self.PACKET_HEADER.unpack_from(self.buffer)
            except struct.error:
                # Not enough data.
                break

            end_offset = self.PACKET_HEADER.size + length
            if len(self.buffer) < end_offset:
                # Still not enough data.
                break

            raw_message = self.buffer[self.PACKET_HEADER.size:end_offset]
            message = self.PACKET_TYPES[type]()
            message.ParseFromString(bytes(raw_message))
            self.message_received(message)
            self.buffer[:] = self.buffer[end_offset:]

    def message_received(self, message):
        logger.debug('<-- %s\n%s', message.__class__.__name__, message)
        handler_name = 'mumble{}_received'.format(
            re.sub('[A-Z]', lambda x: '_' + x.group(0).lower(),
                   message.__class__.__name__))

        try:
            handler = getattr(self, handler_name)
        except AttributeError:
            logger.warn('Message %s unhandled.', message.__class__.__name__)
        else:
            handler(message)

    def mumble_version_received(self, message):
        pass

    def mumble_crypt_setup_received(self, message):
        self.crypt_setup = message

    def mumble_channel_state_received(self, message):
        self.store.add_channel(message)

    def mumble_channel_remove_received(self, message):
        self.store.remove_channel(message.channel_id)

    def mumble_user_state_received(self, message):
        self.store.add_user(message)

    def mumble_user_remove_received(self, message):
        self.store.remove_user(message.session)

    def mumble_server_state_received(self, message):
        self.server_state = message

    def mumble_server_config_received(self, message):
        self.server_config = message

    def send_message(self, message):
        logger.debug('--> %s\n%s', message.__class__.__name__, message)
        raw_message = message.SerializeToString()
        self.transport.write(self.PACKET_HEADER.pack(
            self.PACKET_NUMBERS[message.__class__], len(raw_message)))
        self.transport.write(raw_message)

import asyncio
import logging
import platform
import re
import struct
import time

from .. import Mumble_pb2


logger = logging.getLogger(__name__)


class UDPTunnelTransport(asyncio.DatagramTransport):
    def __init__(self, control_protocol):
        self.control_protocol = control_protocol

    def sendto(self, data, addr=None):
        assert addr is None
        self.control_protocol.send_payload(
            self.client.PACKET_NUMBERS[Mumble_pb2.UDPTunnel], data)


class Protocol(asyncio.Protocol):
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

    def __init__(self, client, username, password):
        self.client = client
        self.username = username
        self.password = password
        self.buffer = bytearray()
        self._ping_handler = None

    def connection_made(self, transport):
        self.transport = transport
        self.udp_tunnel = UDPTunnelTransport(self)

        self.client.control_connection_made()
        self.send_version()
        self.authenticate(self.username, self.password)
        self.start_ping()

    def connection_lost(self, exc):
        if self._ping_handler is not None:
            self._ping_handler.cancel()

    def start_ping(self):
        self.send_message(Mumble_pb2.Ping(timestamp=int(time.time())))
        self._ping_handler = self.client.loop.call_later(20, self.start_ping)

    def send_version(self):
        self.send_message(Mumble_pb2.Version(
            version=self.encode_version(*self.client.MUMBLE_VERSION),
            release='.'.join(str(x) for x in self.client.MUMBLE_VERSION),
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

            raw_message = bytes(self.buffer[self.PACKET_HEADER.size:end_offset])
            self.buffer[:] = self.buffer[end_offset:]

            assert len(raw_message) == length

            packet_cls = self.PACKET_TYPES[type]

            if packet_cls is Mumble_pb2.UDPTunnel:
                self.mumble_udp_tunnel_received(raw_message)
                continue

            message = packet_cls()
            message.ParseFromString(raw_message)
            self.message_received(message)

    def message_received(self, message):
        logger.debug('<-- %s\n%s', message.__class__.__name__, message)
        handler_name = 'mumble{}_received'.format(
            re.sub('[A-Z]+', lambda x: '_' + x.group(0).lower(),
                   message.__class__.__name__))

        try:
            handler = getattr(self, handler_name)
        except AttributeError:
            logger.warn('Message %s unhandled.', message.__class__.__name__)
        else:
            handler(message)

    def mumble_version_received(self, message):
        pass

    def mumble_udp_tunnel_received(self, packet):
        self.client.control_udp_tunnel_received(packet)

    def mumble_codec_version_received(self, message):
        self.client.control_codec_version_received(message.alpha, message.beta,
                                                  message.prefer_alpha,
                                                  message.opus)

    def mumble_crypt_setup_received(self, message):
        self.client.control_crypt_setup_received(
            message.key, message.client_nonce, message.server_nonce)

    def mumble_channel_state_received(self, message):
        self.client.control_channel_state_received(message)

    def mumble_channel_remove_received(self, message):
        self.client.control_channel_remove_received(message.channel_id)

    def mumble_user_state_received(self, message):
        self.client.control_user_state_received(message)

    def mumble_user_remove_received(self, message):
        self.client.control_user_remove_received(message.session)

    def mumble_server_state_received(self, message):
        self.server_state = message

    def mumble_server_config_received(self, message):
        self.server_config = message
        self.client.connection_ready()

    def mumble_ping_received(self, message):
        pass

    def mumble_text_message_received(self, message):
        self.client.control_text_message_received(
            message.actor, message.message, sessions=list(message.session),
            channel_ids=list(message.channel_id))

    def send_payload(self, type, payload):
        self.transport.write(self.PACKET_HEADER.pack(type, len(payload)))
        self.transport.write(payload)

    def send_message(self, message):
        logger.debug('--> %s\n%s', message.__class__.__name__, message)
        self.send_payload(self.PACKET_NUMBERS[message.__class__],
                          message.SerializeToString())

    def send_text_message(self, actor, message, sessions=None, channel_ids=None,
                          tree_ids=None):
        msg = Mumble_pb2.TextMessage(actor=actor, message=message)

        if sessions is not None:
            msg.session.extend(sessions)

        if channel_ids is not None:
            msg.channel_id.extend(channel_ids)

        if tree_ids is not None:
            msg.tree_id.extend(tree_ids)

        self.send_message(msg)

    def move_user(self, actor, session, channel_id):
        self.send_message(Mumble_pb2.UserState(actor=actor, session=session,
                                               channel_id=channel_id))

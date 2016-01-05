import asyncio
import collections
import enum
import logging
import re
import struct


logger = logging.getLogger(__name__)

CELT_CODECS = {}

try:
    from ..codecs import celt011
except Exception as e:
    logger.warn('Could not load celt-0.11: %s', e)
else:
    CELT_CODECS[celt011.BITSTREAM_VERSION] = celt011

try:
    from ..codecs import celt07
except Exception as e:
    logger.warn('Could not load celt-0.7: %s', e)
else:
    CELT_CODECS[celt07.BITSTREAM_VERSION] = celt07


class Protocol(asyncio.DatagramProtocol):
    POSITION_FORMAT = struct.Struct('!fff')
    SAMPLE_RATE = 48000

    class PacketType(enum.IntEnum):
        VOICE_CELT_ALPHA = 0
        PING = 1
        VOICE_SPEEX = 2
        VOICE_CELT_BETA = 3
        VOICE_OPUS = 4

    class Target(enum.IntEnum):
        NORMAL = 0
        SERVER_LOOPBACK = 31

    VoiceTarget = collections.namedtuple('VoiceTarget', ['value'])

    @classmethod
    def _target_to_type(cls, target):
        try:
            return cls.Target(target)
        except ValueError:
            return cls.VoiceTarget(target)

    def __init__(self, client):
        self.client = client
        self.codecs = {}
        self.outgoing_codec = None

    def connection_made(self, transport):
        self.transport = transport

    def setup_crypt(self, key, client_nonce, server_nonce):
        # TODO: cry a lot
        return

    def setup_codecs(self, alpha, beta, prefer_alpha, opus):
        if alpha:
            self.codecs[self.PacketType.VOICE_CELT_ALPHA] = \
                CELT_CODECS[alpha & 0xffffffff].Codec(self.SAMPLE_RATE)

        if beta:
            self.codecs[self.PacketType.VOICE_CELT_BETA] = \
                CELT_CODECS[beta & 0xffffffff].Codec(self.SAMPLE_RATE)

        if prefer_alpha:
            self.outgoing_codec = self.codecs[self.PacketType.VOICE_CELT_ALPHA]
        else:
            self.outgoing_codec = self.codecs[self.PacketType.VOICE_CELT_BETA]

        if opus:
            raise Exception('opus not supported yet')

    def datagram_received(self, data, addr):
        pass

    def plaintext_data_received(self, data):
        header, payload = data[0], data[1:]

        type = self.PacketType(header >> 5)
        target = self._target_to_type(header & 0b11111)

        if type == self.PacketType.PING:
            ts, _ = self._decode_varint(payload)
            logger.debug('<-- type: %s\ntime: %d', type, ts)
            self.send_voice_data(type, target, payload)
            return

        if type not in self.codecs:
            logger.warn('No codec for voice type: %s', type)

        session, payload = self._decode_varint(payload)
        sequence_number, payload = self._decode_varint(payload)

        # TODO: handle sequence number

        more_frames = True
        while more_frames:
            if type == self.PacketType.VOICE_OPUS:
                audio_header, payload = self._decode_varint(payload)
                length = audio_header & 0b1111111111111
                terminated = audio_header >> 13 == 1
                more_frames = False
                frame, payload = payload[:length], payload[length:]
            else:
                audio_header, payload = payload[0], payload[1:]
                length = audio_header & 0b1111111
                terminated = length == 0
                more_frames = audio_header >> 7 == 1
                frame, payload = payload[:length], payload[length:]

            logger.debug('<-- type: %s\nsession: %d\nlength: %s\n'
                         'terminated: %r\nmore_frames: %r\nframe: %d bytes',
                         type, session, length, terminated, more_frames,
                         len(frame))

            if frame:
                pcm = self.codecs[type].decoder.decode(frame)
                self.client.voice_packet_received(session, target, pcm)

    def _decode_varint(self, payload):
        if payload[0] & 0b10000000 == 0:
            return payload[0] & 0b01111111, payload[1:]
        elif payload[0] & 0b01000000 == 0:
            return (payload[0] & 0b00111111 << 8) | payload[1], payload[2:]
        elif payload[0] & 0b00100000 == 0:
            return (payload[0] & 0b00011111 << 16) | (payload[1] << 8) | \
                   payload[2], payload[3:]
        elif payload[0] & 0b00010000 == 0:
            return (payload[0] & 0b00001111 << 24) | (payload[1] << 16) | \
                   (payload[2] << 8) | payload[3], payload[4:]
        elif payload[0] & 0b00001100 == 0:
            return (payload[1] << 16) | (payload[2] << 16) | \
                   (payload[3] << 8) | (payload[4]), payload[5:]
        elif payload[0] & 0b00001100 == 1:
            return (payload[1] << 56) | (payload[2] << 48) | \
                   (payload[3] << 40) | (payload[4] << 32) | \
                   (payload[5] << 24) | (payload[6] << 16) | \
                   (payload[7] << 8) |  payload[8], payload[9:]
        elif payload[0] & 0b00001100 == 2:
            val, payload = self._decode_varint(payload[1:])
            return -val, payload
        elif payload[0] & 0b00001100 == 2:
            return -(payload[0] & 0b00000011), payload[1:]

    def send_voice_data(self, type, target, payload):
        logger.debug('--> type: %s\ntarget: %s\npayload: %d bytes',
                     type, target, len(payload))
        self.transport.sendto(bytes([type.value << 5 | target.value]) + payload)

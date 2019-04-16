import io


SYNC_MARKER = b'\x06\xa6\xa6\xa6\xa6\xa6\xa6'


sample_rates = [8000, 12000, 16000, 24000, 48000]


def parse_packet(_io):
    opcode, = _io.read(1)

    if opcode == 0:
        b1, b2 = _io.read(2)
        payload_size = (b1 << 8) | b2
        paload = _io.read(payload_size)
        return ('data', paload)

    if opcode == 1:
        b1, b2 = _io.read(2)
        sample_rate = sample_rates[(b1 & 0xE0) >> 5]
        samples_per_frame = ((b1 & 0x1F) << 8) | b2
        return ('spec', (sample_rate, samples_per_frame))

    if opcode == 2:
        return ('spec_request', None)

    if opcode == 3:
        for i in SYNC_MARKER:
            if i not in _io.read(1):
                break
        else:
            return ('sync', None)

    if opcode == 3:
        return ('sync_request', None)


def build_packet(op, payload):
    if op == 'data':
        l = len(payload)
        return bytes([0, (l & 0xFF00) >> 8, l & 0xFF]) + payload

    if op == 'spec':
        sample_rate, samples_per_frame = payload
        return bytes([1, ((sample_rates.index(sample_rate) & 0x7) << 5) | ((samples_per_frame & 0x1F00) >> 8), samples_per_frame & 0xFF])

    if op == 'spec_request':
        return bytes([2])


if 0:
    for packet in [b'\x00\x01\x23' + b'\x00' * 0x123, b'\x01\x20\x78', b'\x02']:
        parsed = parse_packet(io.BytesIO(packet))
        print(parsed)
        print(build_packet(*parsed))
        assert build_packet(*parsed) == packet


if 0:
    _io = io.BytesIO(b'\x06\xa6asdf\x06\xa6\xa6' + SYNC_MARKER + b'after sync')
    dont_read = False
    while 1:
        for header_c in SYNC_MARKER:
            if dont_read:
                dont_read = False
            else:
                stream_c = _io.read(1)

            print(_io.tell(), stream_c, bytes([header_c]))

            if header_c not in stream_c:  # Works like "==" but between int and bytes
                if SYNC_MARKER[0] in stream_c:
                    dont_read = True
                break
        else:
            break
    print(_io.read())


if 0:
    _io = io.BytesIO(b'\x06\xa6asdf\x06\xa6\xa6' + SYNC_MARKER + b'after sync')
    i_marker = 0
    c = _io.read(1)
    while 1:
        print(_io.tell(), c, bytes([SYNC_MARKER[i_marker]]))
        if SYNC_MARKER[i_marker] in c:
            i_marker += 1
            if i_marker == len(SYNC_MARKER):
                break
            c = _io.read(1)
            assert c, 'EOF'
            continue

        i_marker = 0
        if SYNC_MARKER[i_marker] not in c:
            c = _io.read(1)
            assert c, 'EOF'

    print(_io.read())


if 0:
    _io = io.BytesIO(b'\x06\xa6asdf\x06\xa6\xa6' + SYNC_MARKER + b'after sync')

    i_marker = 0
    last_c = b''
    c = _io.read(1)

    while 1:
        print(_io.tell(), c, last_c, i_marker, bytes([SYNC_MARKER[i_marker]]))

        if SYNC_MARKER[i_marker] in c:
            i_marker += 1
            if i_marker == len(SYNC_MARKER):
                break
        else:
            i_marker = 0
            if SYNC_MARKER[0] in last_c:
                i_marker += 1
                continue

        last_c = c
        c = _io.read(1)
        assert c, 'EOF'

    print(_io.read())

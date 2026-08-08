MAXPORT = 65535


log = None


def set_logger(logger):
    global log
    log = logger


def _error(message):
    if log:
        log.error(message)


def verify_addr(addrstr):
    port = None
    if not addrstr:
        return False
    if ':' in addrstr:
        addrparts = addrstr.split(':')
        ip = addrparts[0]
        port = int(addrparts[1])
        if (port < 1) or (port > MAXPORT):
            _error(f'Invalid port number: {port}')
            return False
    else:
        ip = addrstr

    if ip:
        ipparts = ip.split('.')
        if len(ipparts) == 4:
            try:
                if all(0 <= int(p) < 256 for p in ipparts):
                    return (ip, port)
            except Exception:
                _error(f'Invalid IP address syntax: {ipparts}')
    _error(f'Invalid IP address: {ip}')
    return False


def verify_id(id):
    idprofile = [8, 4, 4, 4, 12]
    id = id.lower()
    parts = id.split('-')
    if len(parts) == len(idprofile):
        for i in range(len(parts)):
            if len(parts[i]) == idprofile[i]:
                for x in range(len(parts[i])):
                    if parts[i][x] not in '0123456789abcdef':
                        return False
            else:
                return False
    else:
        return False
    return id

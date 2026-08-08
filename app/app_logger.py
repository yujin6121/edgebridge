import datetime
import os
import platform
import sys
import time
import zoneinfo


class Logger(object):

    def __init__(self, toconsole, tofile, fname, append, timezone='UTC'):
        self.toconsole = toconsole
        self.savetofile = tofile
        self.timezone = timezone
        self.os = platform.system()
        if self.os == 'Windows':
            os.system('color')
        if tofile:
            self.filename = fname
            if not append:
                try:
                    os.remove(fname)
                except Exception:
                    pass
        self.buffer = []

    def _ts(self):
        try:
            tz = zoneinfo.ZoneInfo(self.timezone)
            return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            return time.strftime("%Y-%m-%d %H:%M:%S %Z")

    def __savetofile(self, msg):
        with open(self.filename, 'a') as f:
            f.write(f'{self._ts()}  {msg}\n')

    def __outputmsg(self, colormsg, plainmsg, level):
        if self.toconsole:
            print(colormsg)
        if self.savetofile:
            self.__savetofile(plainmsg)
        self.buffer.append({
            'ts': int(time.time() * 1000),
            'level': level,
            'msg': plainmsg,
        })
        if len(self.buffer) > 1000:
            self.buffer.pop(0)

    def info(self, msg):
        self.__outputmsg(f'\033[33m{self._ts()}  \033[96m{msg}\033[0m', msg, 'info')

    def warn(self, msg):
        self.__outputmsg(f'\033[33m{self._ts()}  \033[93m{msg}\033[0m', msg, 'warn')

    def error(self, msg):
        self.__outputmsg(f'\033[33m{self._ts()}  \033[91m{msg}\033[0m', msg, 'error')

    def hilite(self, msg):
        self.__outputmsg(f'\033[33m{self._ts()}  \033[97m{msg}\033[0m', msg, 'hilite')

    def debug(self, msg):
        if len(sys.argv) > 1 and sys.argv[1] == '-d':
            self.__outputmsg(f'\033[33m{self._ts()}  \033[37m{msg}\033[0m', msg, 'debug')

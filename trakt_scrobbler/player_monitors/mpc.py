import os
import re
import confuse
from trakt_scrobbler import logger
from trakt_scrobbler.player_monitors.monitor import WebInterfaceMon


class MPCMon(WebInterfaceMon):
    exclude_import = True
    URL = "http://{ip}:{port}/variables.html"
    CHARSET_PATTERN = re.compile(r'''<\s*meta\s+[^>]*charset\s*=\s*(?:['"]([^'"]+)['"]|([^\s]+))\s*[^>]*>''')
    VARIABLE_PATTERN = re.compile(r'\<p id=\"([a-z]+)\"\>(.*?)\<', re.MULTILINE)
    CONFIG_TEMPLATE = {
        "ip": confuse.String(default="localhost"),
        "port": confuse.String(default="auto-detect"),
        "poll_interval": confuse.Number(default=10),
    }

    def __init__(self, scrobble_queue):
        try:
            self.URL = self.URL.format(**self.config)
        except KeyError:
            logger.exception(f'Check config for correct {self.name} params.')
            return
        super().__init__(scrobble_queue)

    @staticmethod
    def _read_registry_cfg(*paths):
        import winreg
        error = FileNotFoundError
        for path, key in paths:
            try:
                hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError as e:
                error = e
                # try next entry in paths
            else:
                # found!
                break
        else:
            error.filename = ",".join(paths)
            raise error
        return {"port": lambda: winreg.QueryValueEx(hkey, key)[0]}

    def _decodeResponseContent(self, response):
        charsetMatch = next(self.CHARSET_PATTERN.finditer(response.text), None)
        if (charsetMatch == None):
            return response.text
        charset = charsetMatch.group(1) if charsetMatch.group(1) else charsetMatch.group(2)
        return response.content.decode(charset)

    def get_vars(self):
        response = self.sess.get(self.URL)
        text = self._decodeResponseContent(response)
        matches = self.VARIABLE_PATTERN.findall(text)
        return dict(matches)

    def update_status(self):
        variables = self.get_vars()
        # when a file has just started, it may happen that the variables page is
        # pingable, but not populated. So check that variables isn't empty
        if not variables or variables['duration'] == '0':
            self.status = {}
            return
        self.status['state'] = int(variables['state'])
        for key in ('position', 'duration'):
            self.status[key] = int(variables[key]) / 1000
        # instead of stopping, mpc pauses the file at the last second
        if variables['positionstring'] == variables['durationstring']:
            self.status['state'] = 0
        self.status['filepath'] = variables['filepath']


class MPCHCMon(MPCMon):
    exclude_import = os.name != 'nt'
    name = 'mpc-hc'

    @classmethod
    def read_player_cfg(cls, auto_keys=None):
        path = "Software\\MPC-HC\\MPC-HC\\Settings"
        return cls._read_registry_cfg((path, "WebServerPort"))


class MPCBEMon(MPCHCMon):
    exclude_import = os.name != 'nt'
    name = 'mpc-be'

    @classmethod
    def read_player_cfg(cls, auto_keys=None):
        path1, key1 = "Software\\MPC-BE\\WebServer", "Port"
        # old versions can store their port under Settings hkey
        path2, key2 = "Software\\MPC-BE\\Settings", "WebServerPort"
        return cls._read_registry_cfg((path1, key1), (path2, key2))

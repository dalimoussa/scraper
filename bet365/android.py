import base64
from datetime import datetime
import hashlib
import os
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from curl_cffi.requests import Session, get, post
from prettytable import PrettyTable
from tls_client import Session as BogdanSession

from bet365.utils import parse_odds, pretty_print_table

from .message_parser import fix_data, get_parsers, read_table
from .sdk import build_cookies

Bet365ZAP = None

try:
    from .live import Bet365ZAP

    IS_ZAP_AVAILABLE = True
except ImportError:  # not available for demo yet
    IS_ZAP_AVAILABLE = False


def NOT_NULL(_, m):
    return bool(m)


@dataclass
class Sport:
    name: str
    PD: str


TLS_FINGERPRINT = {
    "ja3": "771,4865-4866-4867-49195-49196-52393-49199-49200-52392-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-51-45-43-21,29-23-24,0",
    "akamai": "4:16777216|16711681|0|m,p,a,s",
    "extra_fp": {
        "tls_signature_algorithms": [
            "ecdsa_secp256r1_sha256",
            "rsa_pss_rsae_sha256",
            "rsa_pkcs1_sha256",
            "ecdsa_secp384r1_sha384",
            "rsa_pss_rsae_sha384",
            "rsa_pkcs1_sha384",
            "rsa_pss_rsae_sha512",
            "rsa_pkcs1_sha512",
            "rsa_pkcs1_sha1",
        ]
    },
}


class Bet365AndroidSession:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *args,
        host="www.bet365.com",
        proxy: Optional[str] = None,
        verify=True,
        **kwargs,
    ):
        kwargs.update(TLS_FINGERPRINT)
        self.session = Session(*args, **kwargs)
        if proxy:
            self.session.proxies["https"] = proxy
        self.session.verify = False
        self.proxy = proxy
        self.verify = False
        self.host = host
        self.domain = host if not host.startswith("www.") else host[4:]
        self.api_url = api_url
        self.api_key = api_key
        self._cookie_lock = threading.Lock()
        self.device_id = f"00000000-0000-0000-{os.urandom(2).hex().upper()}-{os.urandom(6).hex().upper()}"
        self.android_id = "5ff3aced6685ab15"  # os.urandom(8).hex()
        self._sst = ""
        self.zap_thread = None
        self.zap = None
        self.config_event = threading.Event()
        self.config_event.wait

    def get_sport_homepage(self, sport: Sport):
        splash_response = self.protected_get(
            f"https://{self.host}/splashcontentapi/getsplashpods",
            params={
                "lid": "1",
                "zid": "9",
                "pd": sport.PD,
                "cid": "143",
                "cgid": "1",
                "ctid": "143",
                "tzo": "60",
            },
            headers={
                "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
                "X-b365App-ID": "8.0.69.00-row",
                "Host": self.host,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            },
            test=True
        )
        match_tables = []
        for root in get_parsers(splash_response.text):
            has_pod = any(
                root.find_sections(
                    "CL", PV=lambda k, v: v.startswith("podcontentcontentapi")
                )
            )
            if not has_pod:
                continue
            for mg in root.find_sections("MG"):
                table = read_table(mg)
                if not table["data"]:
                    continue
                pretty_print_table(table, self.zap)
                match_tables.append(fix_data(table))

    def extract_available_sports(self) -> list[Sport]:
        r = self.protected_get(
            f"https://{self.host}/leftnavcontentapi/allsportsmenu",
            params={
                "lid": "30",
                "zid": "0",
                "pd": "#AL#B1#R^1#",
                "cid": "13",
                "cgid": "2",
                "ctid": "13",
                "tzo": "660",
            },
            headers={
                "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.120 Gen6 bet365/8.0.69.00",
                "X-b365App-ID": "8.0.69.00-row",
                "Host": self.host,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            },
            verify=False,
        )
        sports = []
        seen_pds = set()
        for root in get_parsers(r.text):
            for node in root.walk():
                if node.type in ("CL", "EV"):
                    raw_pd = node.get_property("PD", "")
                    pd = urllib.parse.unquote(raw_pd) if raw_pd else ""
                    na = node.get_property("NA", "")
                    if pd and na and (pd.startswith("#AS#") or pd.startswith("#AC#")):
                        clean_pd = pd[: -len("K^5#")] if pd.endswith("K^5#") else pd
                        if clean_pd not in seen_pds:
                            seen_pds.add(clean_pd)
                            sports.append(Sport(na, clean_pd))
        return sports

    def go_homepage(self):
        """
        Bootstrap session cookies (especially pstk) through bet365.com, which
        always issues them, then optionally visit the target host (e.g. .fr) for
        locale-specific config. All signed API requests afterwards will carry a
        valid pstk cookie.
        """
        ua = "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.120 Gen6 bet365/8.0.69.00"
        nav_headers = {
            "x-b365app-id": "8.0.69.00-row",
            "sec-ch-ua": '"Android WebView";v="144", "Not?A_Brand";v="8", "Chromium";v="144" Gen6 ',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "upgrade-insecure-requests": "1",
            "user-agent": ua,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "x-requested-with": "com.bet365Wrapper.Bet365_Application",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # ── Phase 1: always hit .com to obtain pstk ──────────────────────────
        com_host = "www.bet365.com"
        r_com_hp = None
        for attempt in range(3):
            try:
                r_com_hp = self.session.get(
                    f"https://{com_host}/",
                    headers={**nav_headers, "referer": f"https://{com_host}"},
                    default_headers=False,
                )
                if r_com_hp.status_code == 200:
                    break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

        assert r_com_hp is not None and r_com_hp.status_code == 200, (
            f"bet365.com homepage blocked ({getattr(r_com_hp, 'status_code', 'error')})"
        )
        for k, v in r_com_hp.cookies.items():
            self.session.cookies[k] = v

        com_config_path = r_com_hp.text.split('"SITE_CONFIG_LOCATION":"')[1].split('"')[0]
        com_config_url = f"https://{com_host}{com_config_path}"

        r_com_cfg = self.session.get(
            com_config_url,
            headers={
                "user-agent": ua,
                "accept": "*/*",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "fr-FR,fr;q=0.9",
                "referer": f"https://{com_host}/",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
            },
            default_headers=False,
        )
        assert r_com_cfg.status_code == 200, (
            f"bet365.com config fetch failed ({r_com_cfg.status_code})"
        )
        # Merge pstk and other session cookies from .com config response
        for k, v in r_com_cfg.cookies.items():
            self.session.cookies[k] = v

        cfg_body = r_com_cfg.text
        if cfg_body.startswith("redirectto:"):
            raise RuntimeError(
                f"bet365.com config was geo-redirected (check IP/proxy):\n{cfg_body[:300]}"
            )

        try:
            cfg_json = r_com_cfg.json()
        except Exception as exc:
            raise RuntimeError(
                f"bet365.com config response not JSON:\n{cfg_body[:300]}"
            ) from exc

        self._sst = cfg_json["ns_weblib_util"]["WebsiteConfig"]["SST"]
        self.session.cookies["usdi"] = f"uqid={self.device_id}"

        # ── Phase 2: if target host != .com, fetch its homepage too ──────────
        # (for locale cookies, but we already have pstk from .com)
        if self.host != com_host:
            r_fr_hp = self.session.get(
                f"https://{self.host}/",
                headers={**nav_headers, "referer": f"https://{self.host}"},
                default_headers=False,
            )
            # Non-fatal: just merge whatever cookies we get
            if r_fr_hp.status_code == 200:
                for k, v in r_fr_hp.cookies.items():
                    if k not in ("pstk", "swt"):   # don't overwrite .com auth cookies
                        self.session.cookies[k] = v

        if IS_ZAP_AVAILABLE and Bet365ZAP:
            self.zap = Bet365ZAP(
                ua,
                self.session.cookies["pstk"],
                r_com_hp.text,
                cfg_json,
            )
            self.zap_thread = self.zap.start()


    def login(self, email, password):
        response = self.protected_post(
            f"https://members.{self.domain}/loginapi/lp/login",
            headers = {
                'Host': f'members.{self.domain}',
                'user-agent': 'Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/148.0.7778.215 Gen6 bet365/8.0.61.00',
                'x-b365app-id': '8.0.61.00-row',
                'content-type': 'application/x-www-form-urlencoded',
            },
            data = {
                'txtType': '47',
                'txtTKN': self.session.cookies["pstk"],
                'txtFlashVersion': 'androidApp',
                'platform': '71',
                'txtUNEM': email,
                'txtPassword': password,
                'AuthenticationMethod': '0',
                'txtScreenSize': '392.72726 x 803.63635',
            }
        )
        self.session.cookies.update(response.cookies)
    def get_balance(self):
        response = self.protected_get(
            url=f"https://{self.host}/pam/balanceapi/balance",
            params={
                'lid': '30',
                'zid': '0',
                'pd': "#BABA#",
                'cid': '13',
                'cgid': '2',
                'ctid': '13',
                'csid': '95',
            },
            headers={
                "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
                "X-b365App-ID": "8.0.69.00-row",
                "Host": self.host,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            },
        )
        raise NotImplementedError("I didn't implement parsing balance but here is the response: " + response.text)
    def protected_post(
        self,
        url: str,
        data: Union[str, bytes, Dict[str, Any]],
        headers: Union[dict[str, str], None] = None,
        *args,
        **kwargs,
    ):
        """POST with X-Net-Sync-Term-Android (post body is hashed for the token)."""
        headers = dict(headers or {})
        if isinstance(data, dict):
            post_bytes = urllib.parse.urlencode(data).encode("utf-8")
        elif isinstance(data, str):
            post_bytes = data.encode("utf-8")
        else:
            post_bytes = data

        cookie_header = build_cookies(self.session.cookies)
        headers["Cookie"] = cookie_header
        headers["X-Net-Sync-Term-Android"] = self.get_x_net_header(
            url, cookie_header, post_bytes
        )
        headers["Content-Length"] = str(len(post_bytes))

        kwargs["default_headers"] = False
        kwargs.update(TLS_FINGERPRINT)
        kwargs.update({"proxy": self.proxy, "verify": self.verify})
        response = post(
            url,
            data=post_bytes,
            headers=headers,
            http_version="v1",
            *args,
            **kwargs,
        )
        #parsed = self._parse_set_cookie_headers(response)
        #if parsed:
        #    for k, v in parsed.items():
        #        self.session.cookies[k] = v
        #else:
        #    self._merge_response_cookies(response)
        return response


    def protected_get(
        self, url: str, headers: Union[dict[str, str], None] = None, *args, test=False, **kwargs
    ):
        headers = headers or {}

        # Build a minimal cookie string sufficient for public (non-logged-in) endpoints
        try:
            pstk = self.session.cookies["pstk"]
            cookie_header = (
                "aps03=cf=N&cg=1&cst=0&ct=143&hd=N&lng=1&oty=2&tzi=4; "
                f"pstk={pstk}"
            )
        except KeyError:
            # pstk not yet set – use whatever cookies exist
            cookie_header = build_cookies(self.session.cookies)

        headers["Cookie"] = cookie_header
        kwargs["default_headers"] = False
        kwargs.update(TLS_FINGERPRINT)

        # Bake query-string params into the URL so the token is signed over the
        # exact URL that will be sent, then remove 'params' from kwargs to
        # prevent curl_cffi from appending them a second time.
        params = kwargs.pop("params", {})
        if params:
            parsed_url = urllib.parse.urlparse(url)
            qs = urllib.parse.urlencode(params)
            url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{qs}"

        headers["X-Net-Sync-Term-Android"] = self.get_x_net_header(
            url, cookie_header, b""
        )
        headers["Cookie"] = cookie_header
        kwargs.update({"proxy": self.proxy, "verify": self.verify})

        for attempt in range(3):
            try:
                response = get(url, headers=headers, http_version="v1", *args, **kwargs)
                return response
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def get_x_net_header(self, url: str, cookie_header: str, post_data: bytes) -> str:
        response = BogdanSession().post(
            self.api_url,
            headers={"x-net-api-key": self.api_key},
            json={
                "url": url,
                "cookie": cookie_header,
                "post_hash": base64.b64encode(
                    hashlib.sha256(post_data).digest()
                ).decode(),
                "sst": self._sst,
                "device_id": self.device_id,
            },
        )
        assert response.status_code == 200, (
            "An error occured while generating token: " + response.text
        )
        return response.text

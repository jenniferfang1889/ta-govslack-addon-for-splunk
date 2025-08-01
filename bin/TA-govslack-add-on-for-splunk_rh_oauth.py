"""
This module will be used to get oauth token from auth code
"""
import import_declare_test

import urllib
try:
    from urllib import urlencode
except:
    from urllib.parse import urlencode
from httplib2 import Http, ProxyInfo, socks
import splunk.admin as admin
from solnlib import log
from solnlib import conf_manager
from solnlib.conf_manager import InvalidHostnameError, InvalidPortError
from solnlib.utils import is_true
import json


log.Logs.set_context()
logger = log.Logs().get_logger('ta_slack_add_on_for_splunk_rh_oauth2_token')

# Map for available proxy type
_PROXY_TYPE_MAP = {
    'http': socks.PROXY_TYPE_HTTP,
    'socks4': socks.PROXY_TYPE_SOCKS4,
    'socks5': socks.PROXY_TYPE_SOCKS5,
}

if hasattr(socks, 'PROXY_TYPE_HTTP_NO_TUNNEL'):
    _PROXY_TYPE_MAP['http_no_tunnel'] = socks.PROXY_TYPE_HTTP_NO_TUNNEL

"""
REST Endpoint of getting token by OAuth2 in Splunk Add-on UI Framework. T
"""


class ta_slack_add_on_for_splunk_rh_oauth2_token(admin.MConfigHandler):

    """
    This method checks which action is getting called and what parameters are required for the request.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        session_key = self.getSessionKey()
        log_level = conf_manager.get_log_level(
            logger=logger,
            session_key=session_key,
            app_name="TA-govslack-add-on-for-splunk",
            conf_name="ta-govslack-add-on-for-splunk_settings",
            log_stanza="logging",
            log_level_field="loglevel"
        )
        log.Logs().set_level(log_level)

    def setup(self):
        if self.requestedAction == admin.ACTION_EDIT:
            # Add required args in supported args
            for arg in ('url', 'method',
                        'grant_type', 'client_id',
                        'client_secret'):
                self.supportedArgs.addReqArg(arg)

            for arg in (
                'scope',  # Optional for client_credentials
                'code',  # Required for authorization_code
                'redirect_uri',  # Required for authorization_code
            ):
                self.supportedArgs.addOptArg(arg)
        return

    """
    This handler is to get access token from the auth code received
    It takes 'url', 'method', 'grant_type', 'code', 'client_id', 'client_secret', 'redirect_uri' as caller args and
    Returns the confInfo dict object in response.
    """

    def handleEdit(self, confInfo):

        try:
            logger.debug("In OAuth rest handler to get access token")
            # Get args parameters from the request
            url = self.callerArgs.data['url'][0]
            logger.debug("oAUth url %s", url)
            proxy_info = self.getProxyDetails()

            http = Http(proxy_info=proxy_info)
            method = self.callerArgs.data['method'][0]

            # Create payload from the arguments received
            grant_type = self.callerArgs.data['grant_type'][0]

            payload = {
                'grant_type': self.callerArgs.data['grant_type'][0],
                'client_id': self.callerArgs.data['client_id'][0],
                'client_secret': self.callerArgs.data['client_secret'][0],
            }

            if grant_type == "authorization_code":
                # If grant_type is authorization_code then add code and redirect_uri in payload
                for param_name in ('code', 'redirect_uri'):
                    param = self.callerArgs.data.get(param_name, [None])[0]

                    if param is None:
                        raise ValueError(
                            "%s is required for authorization_code grant type" % param_name
                        )

                    payload[param_name] = param
            elif grant_type == "client_credentials":
                # If grant_type is client_credentials add scope exists then add it in payload
                scope = self.callerArgs.data.get('scope', [None])[0]

                if scope:
                    payload['scope'] = scope
            else:
                # Else raise an error
                logger.error("Invalid grant_type %s", grant_type)
                raise ValueError(
                    "Invalid grant_type %s. Supported values are authorization_code and client_credentials" % grant_type
                )

            headers = {"Content-Type": "application/x-www-form-urlencoded", }
            # Send http request to get the accesstoken
            resp, content = http.request(url,
                                         method=method,
                                         headers=headers,
                                         body=urlencode(payload))
            content = json.loads(content)
            # Check for any errors in response. If no error then add the content values in confInfo
            if resp.status == 200:
                for key, val in content.items():
                    # Retrieve the User OAuth token (NOT the Bot token)
                    if key == 'authed_user':
                        for k, v in val.items():
                            confInfo['token'][k] = v
            else:
                # Else add the error message in the confinfo
                confInfo['token']['error'] = content['error_description']
            logger.info(
                "Exiting OAuth rest handler after getting access token with response %s", resp.status)
        except Exception as exc:
            logger.exception(
                "Error occurred while getting accesstoken using auth code")
            raise

    """
    This method is to get proxy details stored in settings conf file
    """

    def getProxyDetails(self):
        proxy_config = None

        try: 
            proxy_config = conf_manager.get_proxy_dict(
                logger=logger,
                session_key=self.getSessionKey(),
                app_name="TA-govslack-add-on-for-splunk",
                conf_name="ta-govslack-add-on-for-splunk_settings",
            )

        # Handle invalid port case
        except InvalidPortError as e:
            logger.error(f"Proxy configuration error: {e}")

        # Handle invalid hostname case
        except InvalidHostnameError as e:
            logger.error(f"Proxy configuration error: {e}")

        if not proxy_config or not is_true(proxy_config.get('proxy_enabled')):
            logger.info('Proxy is not enabled')
            return None

        url = proxy_config.get('proxy_url')
        port = proxy_config.get('proxy_port')

        user = proxy_config.get('proxy_username')
        password = proxy_config.get('proxy_password')

        if not all((user, password)):
            logger.info('Proxy has no credentials found')
            user, password = None, None

        proxy_type = proxy_config.get('proxy_type')
        proxy_type = proxy_type.lower() if proxy_type else 'http'

        if proxy_type in _PROXY_TYPE_MAP:
            ptv = _PROXY_TYPE_MAP[proxy_type]
        elif proxy_type in _PROXY_TYPE_MAP.values():
            ptv = proxy_type
        else:
            ptv = socks.PROXY_TYPE_HTTP
            logger.info('Proxy type not found, set to "HTTP"')

        rdns = is_true(proxy_config.get('proxy_rdns'))

        proxy_info = ProxyInfo(
            proxy_host=url,
            proxy_port=int(port),
            proxy_type=ptv,
            proxy_user=user,
            proxy_pass=password,
            proxy_rdns=rdns
        )
        return proxy_info

    """
    Method to check if the given port is valid or not
    :param port: port number to be validated
    :type port: ``int``
    """

if __name__ == "__main__":
    admin.init(ta_slack_add_on_for_splunk_rh_oauth2_token, admin.CONTEXT_APP_AND_USER)

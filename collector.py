from prometheus_client.core import GaugeMetricFamily

import requests
import logging
import os
import time
import sys
import re
from collectors.performance_collector import PerformanceCollector
from collectors.firmware_collector import FirmwareCollector
from collectors.health_collector import HealthCollector
from collectors.certificate_collector import CertificateCollector

class RedfishMetricsCollector(object):

    def __enter__(self):
        return self

    def __init__(self, config, target, host, usr, pwd, metrics_type):
        self.target = target
        self.host = host

        self._username = usr
        self._password = pwd
        
        self.metrics_type = metrics_type
        self.collect_certificates = bool(config.get('collect_certificates', False))

        self._timeout = int(os.getenv("TIMEOUT", config.get('timeout', 10)))
        self.labels = {"host": self.host}
        self._redfish_up = 0
        self._response_time = 0
        self._last_http_code = 0
        self.powerstate = 0

        self.urls = {
            "Systems": "",
            "SessionService": "",
            "Memory": "",
            "ManagedBy": "",
            "Processors": "",
            "Storage": "",
            "Chassis": "",
            "Power": "",
            "Thermal": "",
            "PowerSubsystem": "",
            "ThermalSubsystem": "",
            "NetworkInterfaces": "",
        }

        self.server_health = 0

        self.manufacturer = ""
        self.model = ""
        self.serial = ""
        self.status = {
            "ok": 0,
            "operable": 0,
            "enabled": 0,
            "good": 0,
            "critical": 1,
            "error": 1,
            "warning": 2,
            "absent": 0
        }
        self._start_time = time.time()

        self._session_url = ""
        self._auth_token = ""
        self._basic_auth = False
        self._session = ""
        self.redfish_version = "not available"

    def get_session(self):
        # Get the url for the server info and messure the response time
        logging.info(f"Target {self.target}: Connecting to server {self.host}")
        start_time = time.time()
        server_response = self.connect_server("/redfish/v1", noauth=True)

        self._response_time = round(time.time() - start_time, 2)
        logging.info(f"Target {self.target}: Response time: {self._response_time} seconds.")

        if not server_response:
            logging.warning(f"Target {self.target}: No data received from server {self.host}!")
            return

        logging.debug(f"Target {self.target}: data received from server {self.host}.")

        if "RedfishVersion" in server_response:
            self.redfish_version = server_response['RedfishVersion']
        
        for key in ["Systems", "SessionService"]:
            if key in server_response:
                self.urls[key] = server_response[key]['@odata.id']
            else:
                logging.warning(f"Target {self.target}: No {key} URL found on server {self.host}!")
                return

        session_service = self.connect_server(
            self.urls['SessionService'], 
            basic_auth=True
        )

        if self._last_http_code != 200:
            logging.warning(f"Target {self.target}: Failed to get a session from server {self.host}!")
            self._basic_auth = True
            return

        sessions_url = f"https://{self.target}{session_service['Sessions']['@odata.id']}"
        session_data = {"UserName": self._username, "Password": self._password}
        self._session.auth = None
        result = ""

        # Try to get a session
        try:
            result = self._session.post(
                sessions_url, json=session_data, verify=False, timeout=self._timeout
            )
            result.raise_for_status()

        except requests.exceptions.ConnectionError as err:
            logging.warning(f"Target {self.target}: Failed to get an auth token from server {self.host}. Retrying ...")
            try:
                result = self._session.post(
                    sessions_url, json=session_data, verify=False, timeout=self._timeout
                )
                result.raise_for_status()

            except requests.exceptions.ConnectionError as err:
                logging.error(f"Target {self.target}: Error getting an auth token from server {self.host}: {err}")
                self._basic_auth = True

        except requests.exceptions.HTTPError as err:
            logging.warning(f"Target {self.target}: No session received from server {self.host}: {err}")
            logging.warning(f"Target {self.target}: Switching to basic authentication.")
            self._basic_auth = True

        except requests.exceptions.ReadTimeout as err:
            logging.warning(f"Target {self.target}: No session received from server {self.host}: {err}")
            logging.warning(f"Target {self.target}: Switching to basic authentication.")
            self._basic_auth = True

        if result:
            if result.status_code in [200, 201]:
                self._auth_token = result.headers['X-Auth-Token']
                self._session_url = result.json()['@odata.id']
                logging.info(f"Target {self.target}: Got an auth token from server {self.host}!")
                self._redfish_up = 1

    def connect_server(self, command, noauth=False, basic_auth=False):
        logging.captureWarnings(True)

        req = ""
        req_text = ""
        server_response = ""
        self._last_http_code = 200
        request_duration = 0
        request_start = time.time()

        url = f"https://{self.target}{command}"

        # check if we already established a session with the server
        if not self._session:
            self._session = requests.Session()
        else:
            logging.debug(f"Target {self.target}: Using existing session.")

        self._session.verify = False
        self._session.headers.update({"charset": "utf-8"})
        self._session.headers.update({"content-type": "application/json"})

        if noauth:
            logging.debug(f"Target {self.target}: Using no auth")
        elif basic_auth or self._basic_auth:
            self._session.auth = (self._username, self._password)
            logging.debug(f"Target {self.target}: Using basic auth with user {self._username}")
        else:
            logging.debug(f"Target {self.target}: Using auth token")
            self._session.auth = None
            self._session.headers.update({"X-Auth-Token": self._auth_token})

        logging.debug(f"Target {self.target}: Using URL {url}")
        try:
            req = self._session.get(url, stream=True, timeout=self._timeout)
            req.raise_for_status()

        except requests.exceptions.HTTPError as err:
            self._last_http_code = err.response.status_code
            if err.response.status_code == 401:
                logging.error(f"Target {self.target}: Authorization Error: Wrong job provided or user/password set wrong on server {self.host}: {err}")
            else:
                logging.error(f"Target {self.target}: HTTP Error on server {self.host}: {err}")

        except requests.exceptions.ConnectTimeout:
            logging.error(f"Target {self.target}: Timeout while connecting to {self.host}")
            self._last_http_code = 408

        except requests.exceptions.ReadTimeout:
            logging.error(f"Target {self.target}: Timeout while reading data from {self.host}")
            self._last_http_code = 408

        except requests.exceptions.ConnectionError as err:
            logging.error(f"Target {self.target}: Unable to connect to {self.host}: {err}")
            self._last_http_code = 444
        except:
            logging.error(f"Target {self.target}: Unexpected error: {sys.exc_info()[0]}")
            self._last_http_code = 500

        if req != "":
            self._last_http_code = req.status_code
            try:
                req_text = req.json()

            except:
                logging.debug(f"Target {self.target}: No json data received.")

            # req will evaluate to True if the status code was between 200 and 400 and False otherwise.
            if req:
                server_response = req_text

            # if the request fails the server might give a hint in the ExtendedInfo field
            else:
                if req_text:
                    logging.debug(f"Target {self.target}: {req_text['error']['code']}: {req_text['error']['message']}")

                    if "@Message.ExtendedInfo" in req_text['error']:

                        if type(req_text['error']['@Message.ExtendedInfo']) == list:
                            if ("Message" in req_text['error']['@Message.ExtendedInfo'][0]):
                                logging.debug(f"Target {self.target}: {req_text['error']['@Message.ExtendedInfo'][0]['Message']}")

                        elif type(req_text['error']['@Message.ExtendedInfo']) == dict:

                            if "Message" in req_text['error']['@Message.ExtendedInfo']:
                                logging.debug(f"Target {self.target}: {req_text['error']['@Message.ExtendedInfo']['Message']}")
                        else:
                            pass

        request_duration = round(time.time() - request_start, 2)
        logging.debug(f"Target {self.target}: Request duration: {request_duration}")
        return server_response

    def get_base_labels(self):
        systems = self.connect_server(self.urls['Systems'])

        if not systems:
            return

        power_states = {"off": 0, "on": 1}
        # Get the server info for the labels
        server_info = self.connect_server(systems['Members'][0]['@odata.id'])
        if not server_info:
            return
        self.manufacturer = server_info['Manufacturer']
        self.model = server_info['Model']
        self.powerstate = power_states[server_info['PowerState'].lower()]
        # Dell has the Serial# in the SKU field, others in the SerialNumber field.
        self.serial = server_info['SKU'] if "SKU" in server_info and re.match(r'^[Dd]ell.*', server_info['Manufacturer']) else server_info['SerialNumber']

        self.labels.update(
            {
                "host": self.host,
                "server_manufacturer": self.manufacturer,
                "server_model": self.model,
                "server_serial": self.serial
            }
        )

        self.server_health = self.status[server_info['Status']['Health'].lower()]

        # get the links of the parts for later
        for key in self.urls.keys():
            if key in server_info:
                self.urls[key] = server_info[key]['@odata.id']

        # standard is a list but there are exceptions
        if type(server_info['Links']['Chassis'][0]) == str:
            self.urls['Chassis'] = server_info['Links']['Chassis'][0]
            self.urls['ManagedBy'] = server_info['Links']['ManagedBy'][0]
        else:
            self.urls['Chassis'] = server_info['Links']['Chassis'][0]['@odata.id']
            self.urls['ManagedBy'] = server_info['Links']['ManagedBy'][0]['@odata.id']

        self.get_chassis_urls()

    def get_chassis_urls(self):
        chassis_data = self.connect_server(self.urls['Chassis'])
        if not chassis_data:
            return

        urls = ['PowerSubsystem', 'Power', 'ThermalSubsystem', 'Thermal']
        
        for url in urls:
            if url in chassis_data:
                self.urls[url] = chassis_data[url]['@odata.id']

        return chassis_data
    

    def collect(self):
        if self.metrics_type == 'health':
            up_metrics = GaugeMetricFamily(
                f"redfish_up",
                "Redfish Server Monitoring availability",
                labels = self.labels,
            )
            up_metrics.add_sample(
                f"redfish_up", 
                value = self._redfish_up, 
                labels = self.labels
            )
            yield up_metrics

            version_metrics = GaugeMetricFamily(
                f"redfish_version",
                "Redfish Server Monitoring redfish version",
                labels = self.labels,
            )
            version_labels = {'version': self.redfish_version}
            version_labels.update(self.labels)
            version_metrics.add_sample(
                f"redfish_version", 
                value = 1, 
                labels = version_labels
            )
            yield version_metrics

            response_metrics = GaugeMetricFamily(
                f"redfish_response_duration_seconds",
                "Redfish Server Monitoring response time",
                labels = self.labels,
            )
            response_metrics.add_sample(
                f"redfish_response_duration_seconds",
                value = self._response_time,
                labels = self.labels,
            )
            yield response_metrics
            
        if self._redfish_up == 0:
            return

        self.get_base_labels()

        if self.metrics_type == 'health':

            if self.collect_certificates:
                cert_metrics = CertificateCollector(self.host, self.target, self.labels)
                cert_metrics.collect()

                yield cert_metrics.cert_metrics_isvalid
                yield cert_metrics.cert_metrics_valid_hostname
                yield cert_metrics.cert_metrics_valid_days
                yield cert_metrics.cert_metrics_selfsigned

            powerstate_metrics = GaugeMetricFamily(
                "redfish_powerstate",
                "Redfish Server Monitoring Power State Data",
                labels = self.labels,
            )
            powerstate_metrics.add_sample(
                "redfish_powerstate", value = self.powerstate, labels = self.labels
            )
            yield powerstate_metrics

            metrics = HealthCollector(self)
            metrics.collect()

            yield metrics.mem_metrics_correctable
            yield metrics.mem_metrics_unorrectable
            yield metrics.health_metrics

        # Get the firmware information
        if self.metrics_type == 'firmware':
            metrics = FirmwareCollector(self)
            metrics.collect()
                
            yield metrics.fw_metrics

        # Get the performance information
        if self.metrics_type == 'performance':
            metrics = PerformanceCollector(self)
            metrics.collect()
            
            yield metrics.power_metrics
            yield metrics.temperature_metrics

        # Finish with calculating the scrape duration
        duration = round(time.time() - self._start_time, 2)
        logging.info(f"Target {self.target}: {self.metrics_type} scrape duration: {duration} seconds")

        scrape_metrics = GaugeMetricFamily(
            f"redfish_{self.metrics_type}_scrape_duration_seconds",
            f"Redfish Server Monitoring redfish {self.metrics_type} scrabe duration in seconds",
            labels = self.labels,
        )

        scrape_metrics.add_sample(
            f"redfish_{self.metrics_type}_scrape_duration_seconds",
            value = duration,
            labels = self.labels,
        )
        yield scrape_metrics

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.debug(f"Target {self.target}: Deleting Redfish session with server {self.host}")

        if self._auth_token:
            session_url = f"https://{self.target}{self._session_url}"
            headers = {"x-auth-token": self._auth_token}

            logging.debug(f"Target {self.target}: Using URL {session_url}")

            response = requests.delete(
                session_url, verify=False, timeout=self._timeout, headers=headers
            )
            response.close()

            if response:
                logging.info(f"Target {self.target}: Redfish Session deleted successfully.")
            else:
                logging.warning(f"Target {self.target}: Failed to delete session with server {self.host}")
                logging.warning(f"Target {self.target}: Token: {self._auth_token}")

        else:
            logging.debug(f"Target {self.target}: No Redfish session existing with server {self.host}")

        if self._session:
            logging.info(f"Target {self.target}: Closing requests session.")
            self._session.close()

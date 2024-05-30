from prometheus_client.core import GaugeMetricFamily

import logging
import math

class HealthCollector(object):

    def __enter__(self):
        return self

    def __init__(self, redfish_metrics_collector):

        self.col = redfish_metrics_collector

        self.health_metrics = GaugeMetricFamily(
            "redfish_health",
            "Redfish Server Monitoring Health Data",
            labels=self.col.labels,
        )
        self.mem_metrics_correctable = GaugeMetricFamily(
            "redfish_memory_correctable",
            "Redfish Server Monitoring Memory Data for correctable errors",
            labels=self.col.labels,
        )
        self.mem_metrics_unorrectable = GaugeMetricFamily(
            "redfish_memory_uncorrectable",
            "Redfish Server Monitoring Memory Data for uncorrectable errors",
            labels=self.col.labels,
        )

    def get_proc_health(self):
        logging.debug(f"Target {self.col.target}: Get the CPU health data.")
        processor_collection = self.col.connect_server(self.col.urls["Processors"])

        if not processor_collection:
            return
        for processor in processor_collection["Members"]:
            processor_data = self.col.connect_server(processor["@odata.id"])
            
            if not processor_data:
                continue

            if "Health" in processor_data["Status"]:
                proc_status = (
                    math.nan
                    if processor_data["Status"]["Health"] is None
                    else self.col.status[processor_data["Status"]["Health"].lower()]
                )
            else:
                logging.warning(f"Target {self.col.target}: No Processor health data provided for {current_labels['device_name']}!")

            current_labels = {
                "device_type": "processor",
                "device_name": processor_data.get("Socket", "unknown"),
                "device_manufacturer": processor_data.get("Manufacturer", "unknown"),
                "cpu_type": processor_data.get("ProcessorType", "unknown"),
                "cpu_model": processor_data.get("Model", "unknown"),
                "cpu_cores": str(processor_data.get("TotalCores", "unknown")),
                "cpu_threads": str(processor_data.get("TotalThreads", "unknown")),
            }
            current_labels.update(self.col.labels)

            self.health_metrics.add_sample("redfish_health", value=proc_status, labels=current_labels)

    def get_storage_health(self):
        logging.debug(f"Target {self.col.target}: Get the storage health data.")
        storage_collection = self.col.connect_server(self.col.urls["Storage"])

        if not storage_collection:
            return
        for controller in storage_collection["Members"]:
            controller_data = self.col.connect_server(controller["@odata.id"])
            if not controller_data:
                continue
            if controller_data.get("StorageControllers"):
                # Cisco sometimes uses a list or a dict
                if type(controller_data["StorageControllers"]) == list:
                    controller_details = controller_data["StorageControllers"][0]
                else:
                    controller_details = controller_data["StorageControllers"]
            else:
                controller_details = controller_data

            # HPE ILO5 is missing the Name in the details of the controllers
            if "Name" in controller_details:
                controller_name = controller_details["Name"]
            elif "Name" in controller_data:
                controller_name = controller_data["Name"]
            else:
                controller_name = "unknown"

            # Dell BOSS cards use HealthRollup instead of Health
            if "HealthRollup" in controller_details["Status"]:
                controller_status = (
                    math.nan
                    if controller_details["Status"]["HealthRollup"] is None
                    else self.col.status[controller_details["Status"]["HealthRollup"].lower()]
                )
            elif "Health" in controller_details["Status"]:
                # Cisco sometimes uses None as status for onboard controllers
                controller_status = (
                    math.nan
                    if controller_details["Status"]["Health"] is None
                    else self.col.status[controller_details["Status"]["Health"].lower()]
                )
            else:
                logging.warning(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, Controller {controller_name}: No health data found.")

            current_labels = {
                "device_type": "storage",
                "device_name": controller_name,
                "device_manufacturer": controller_details.get("Manufacturer", "unknown"),
                "controller_model": controller_details.get("Model", "unknown"),
            }
            current_labels.update(self.col.labels)

            self.health_metrics.add_sample("redfish_health", value=controller_status, labels=current_labels)

            # Sometimes not all attributes are implemented. Checking if existing one by one.
            disk_attributes = {
                "Name": "device_name",
                "MediaType": "disk_type",
                "Manufacturer": "device_manufacturer",
                "Model": "disk_model",
                "CapacityBytes": "disk_capacity",
                "Protocol": "disk_protocol",
            }
            for disk in controller_data["Drives"]:
                disk_data = self.col.connect_server(disk["@odata.id"])
                if disk_data == "":
                    continue

                current_labels = {"device_type": "disk"}
                for disk_attribute in disk_attributes:
                    if disk_attribute in disk_data:
                        current_labels.update(
                            {
                                disk_attributes[disk_attribute]: str(
                                    disk_data[disk_attribute]
                                )
                            }
                        )

                current_labels.update(self.col.labels)
                if "PredictedMediaLifeLeftPercent" in disk_data:
                    self.health_metrics.add_sample("redfish_health_predicted_media_life_left_percent", value=disk_data["PredictedMediaLifeLeftPercent"], labels=current_labels)

                if "Health" in disk_data["Status"]:
                    disk_status = (
                        math.nan
                        if disk_data["Status"]["Health"] is None
                        else self.col.status[disk_data["Status"]["Health"].lower()]
                    )
                    self.health_metrics.add_sample(
                        "redfish_health", value=disk_status, labels=current_labels
                    )
                else:
                    logging.warning(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, Disk {disk_data['name']}: No health data found.")

    def get_chassis_health(self):
        logging.debug(f"Target {self.col.target}: Get the Chassis health data.")
        chassis_data = self.col.connect_server(self.col.urls["Chassis"])
        if not chassis_data:
            return

        current_labels = {
                "device_type": "chassis", 
                "device_name": chassis_data["Name"]
        }
        current_labels.update(self.col.labels)
        self.health_metrics.add_sample(
            "redfish_health",
            value=self.col.status[chassis_data["Status"]["Health"].lower()],
            labels=current_labels,
        )

    def get_power_health(self):
        logging.debug(f"Target {self.col.target}: Get the PDU health data.")
        power_data = self.col.connect_server(self.col.urls["Power"])
        if not power_data:
            return

        for psu in power_data["PowerSupplies"]:
            psu_name = psu["Name"] if "Name" in psu and psu["Name"] != None else "unknown"
            # HPE ILO5 is missing the PSU Model
            psu_model = psu["Model"] if "Model" in psu and psu["Model"] != None else "unknown"

            current_labels = {
                    "device_type": "powersupply", 
                    "device_name": psu_name, 
                    "device_model": psu_model
            }
            current_labels.update(self.col.labels)
            psu_health = math.nan
            psu_status = dict( (k.lower(), v) for k, v in psu["Status"].items() )  # convert to lower case because there are differences per vendor
            if "state" in psu_status:
                if psu_status["state"] != "absent":
                    if "health" in psu_status:
                        psu_health = ( math.nan if psu_status["health"] is None else self.col.status[psu_status["health"].lower()] )
                    elif "state" in psu_status:
                        psu_health = ( math.nan if psu_status["state"]  is None else self.col.status[psu_status["state"].lower()] )

            if psu_health is math.nan:
                logging.warning(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, PSU {psu_name}: No health data found.")

            self.health_metrics.add_sample(
                "redfish_health", value=psu_health, labels=current_labels
            )

    def get_thermal_health(self):
        logging.debug(f"Target {self.col.target}: Get the thermal health data.")
        thermal_data = self.col.connect_server(self.col.urls["Thermal"])
        if not thermal_data:
            return

        for fan in thermal_data["Fans"]:
            fan_name = fan.get("Name", "unknown")
            current_labels = {
                "device_type": "fan", 
                "device_name": fan_name
            }
            current_labels.update(self.col.labels)
            fan_health = math.nan
            fan_status = dict( (k.lower(), v) for k, v in fan["Status"].items() )  # convert to lower case because there are differences per vendor
            if "state" in fan_status:
                if fan_status["state"] != "absent":
                    if "health" in fan_status:
                        fan_health = (
                            math.nan
                            if fan_status["health"] is None
                            or fan_status["health"] == ""
                            else self.col.status[fan_status["health"].lower()]
                        )
                    elif "state" in fan_status:
                        fan_health = (
                            math.nan
                            if fan_status["state"] is None
                            else self.col.status[fan_status["state"].lower()]
                        )

            if fan_health is math.nan:
                logging.warning(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, Fan {fan['Name']}: No health data found.")

            self.health_metrics.add_sample(
                "redfish_health", value=fan_health, labels=current_labels
            )

    def get_memory_health(self):
        logging.debug(f"Target {self.col.target}: Get the Memory data.")

        memory_collection = self.col.connect_server(self.col.urls["Memory"])
        if not memory_collection:
            return

        for dimm_url in memory_collection["Members"]:
            dimm_info = self.col.connect_server(dimm_url["@odata.id"])

            if not dimm_info:
                continue

            dimm_health = math.nan

            # HPE DL560 Gen10 has no Dimm Status
            if "Status" in dimm_info:
                if type(dimm_info["Status"]) == str:
                    dimm_health = self.col.status[dimm_info["Status"].lower()]
                else:
                    dimm_status = dict( (k.lower(), v) for k, v in dimm_info["Status"].items() )  # convert to lower case because there are differences per vendor

                    if "state" in dimm_status and (dimm_status['state'] == None or dimm_status["state"].lower() == "absent"):
                        logging.debug(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, Dimm {dimm_info['Name']}: absent.")
                        continue

                    if "health" in dimm_status:
                        dimm_health = ( math.nan if dimm_info["Status"]["Health"] is None else self.col.status[dimm_info["Status"]["Health"].lower()] )
                    elif "state" in dimm_status:
                        dimm_health = ( math.nan if dimm_info["Status"]["State"]  is None else self.col.status[dimm_info["Status"]["State"].lower()] )

            if dimm_health is math.nan:
                logging.debug(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}, Dimm {dimm_info['Name']}: No health data found.")

            current_labels = {
                "device_type": "memory", 
                "device_name": dimm_info["Name"],
                "dimm_capacity": str(dimm_info["CapacityMiB"]),
                "dimm_speed": str(dimm_info["OperatingSpeedMhz"]),
                "dimm_type": dimm_info["MemoryDeviceType"],
            }

            if "Manufacturer" in dimm_info:
                manufacturer = dimm_info.get("Manufacturer", "N/A")

            if "Oem" in dimm_info:
                if "Hpe" in dimm_info["Oem"]:
                    manufacturer = dimm_info["Oem"]["Hpe"].get("VendorName", "unknown")

            current_labels.update({"device_manufacturer": manufacturer,})
            current_labels.update(self.col.labels)

            self.health_metrics.add_sample(
                "redfish_health", value=dimm_health, labels=current_labels
            )

            if "Metrics" in dimm_info:
                dimm_metrics = self.col.connect_server(dimm_info["Metrics"]["@odata.id"])
                if not dimm_metrics:
                    continue

                # Lenovo XCC SR650 v3 is missing the entries. Need to catch this.
                if 'CorrectableECCError' in dimm_metrics["HealthData"]["AlarmTrips"]:
                    correctable_ecc_error = (
                        math.nan
                        if dimm_metrics["HealthData"]["AlarmTrips"]["CorrectableECCError"]
                        is None
                        else int(dimm_metrics["HealthData"]["AlarmTrips"]["CorrectableECCError"])
                    )
                    self.mem_metrics_correctable.add_sample("redfish_memory_correctable", value=correctable_ecc_error, labels=current_labels)
                else:
                    logging.debug(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}: Dimm {dimm_info['Name']}: No CorrectableECCError Metrics found.")

                if 'UncorrectableECCError' in dimm_metrics["HealthData"]["AlarmTrips"]:
                    uncorrectable_ecc_error = (
                        math.nan
                        if dimm_metrics["HealthData"]["AlarmTrips"]["UncorrectableECCError"]
                        is None
                        else int(dimm_metrics["HealthData"]["AlarmTrips"]["UncorrectableECCError"])
                    )
                    self.mem_metrics_unorrectable.add_sample("redfish_memory_uncorrectable", value=uncorrectable_ecc_error, labels=current_labels)
                else:
                    logging.debug(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}: Dimm {dimm_info['Name']}: No UncorrectableECCError Metrics found.")

            else:
                logging.debug(f"Target {self.col.target}: Host {self.col.host}, Model {self.col.model}: Dimm {dimm_info['Name']}: No Dimm Metrics found.")

    def collect(self):

        logging.info(f"Target {self.col.target}: Collecting data ...")

        current_labels = {"device_type": "system", "device_name": "summary"}
        current_labels.update(self.col.labels)
        self.health_metrics.add_sample(
            "redfish_health", value=self.col.server_health, labels=current_labels
        )

        # Get the processor health data
        if self.col.urls["Processors"]:
            self.get_proc_health()
        else:
            logging.warning(f"Target {self.col.target}: No Processors URL provided! Cannot get Processors data!")

        # Get the storage health data
        if self.col.urls["Storage"]:
            self.get_storage_health()
        else:
            logging.warning(f"Target {self.col.target}: No Storage URL provided! Cannot get Storage data!")

        # Get the chassis health data
        if self.col.urls["Chassis"]:
            self.get_chassis_health()
        else:
            logging.warning(f"Target {self.col.target}: No Chassis URL provided! Cannot get Chassis data!")

        # Get the powersupply health data
        if self.col.urls["Power"]:
            self.get_power_health()
        else:
            logging.warning(f"Target {self.col.target}: No Power URL provided! Cannot get PSU data!")

        # Get the thermal health data
        if self.col.urls["Thermal"]:
            self.get_thermal_health()
        else:
            logging.warning(f"Target {self.col.target}: No Thermal URL provided! Cannot get thermal data!")

        # Export the memory data
        if self.col.urls["Memory"]:
            self.get_memory_health()
        else:
            logging.warning(f"Target {self.col.target}: No Memory URL provided! Cannot get memory data!")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_tb is not None:
            logging.exception(f"Target {self.target}: An exception occured in {exc_tb.tb_frame.f_code.co_filename}:{exc_tb.tb_lineno}")

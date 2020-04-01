# -*- coding: UTF-8 -*-
#-------------------------------------------------------------------------------
# Name:        BLE MQTT TRansport client - bleTransport service
# Purpose:     Main for the bleTransport servcice - handle MQTT communication
#               and interface towards the BLE Client
#
# Author:      Nicolas Albarel / Laurent Carré
#
# Created:     14/07/2019
# Copyright:   (c) Laurent Carré - Sterwen Technology 2019
# Licence:     Eclipse 1.0
#-------------------------------------------------------------------------------

# update path to include BLE directory
import os
import sys
import inspect

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../BLE_Gateway/BLE-Bluepy")))
sys.path.insert(0, cmd_subfolder)

'''
cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../BLE-OBD")))
sys.path.insert(0, cmd_subfolder)
'''



import logging
import json
import os
import datetime
import argparse
import socket

from time import time
from uuid import getnode
from threading import Thread, Semaphore

from mqtt_wrapper import MQTTWrapper
from utils import ParserHelper
from utils import LoggerHelper

import BLE_Client
import BLE_Data
import Modem_GPS_Client
import OBD_Client
from mqtt_time import *




ble_mqtt_version="2.0.0"
# Global logger
_logger = None

####################################################################
# BLEMQTTService

class SolidSenseMQTTService(BLE_Client.BLE_Service_Callbacks):
    """
    """

    def __init__(self, settings, logger=None, **kwargs):
        super().__init__()

        self.logger = logger or logging.getLogger(__name__)
        self.exitSem = Semaphore(0)

        self.gw_id = settings.gateway_id
        self.gw_model = settings.gateway_model
        self.gw_version = settings.gateway_version

        self.ble_on = settings.ble
        self.ble_filters = settings.ble_filters
        self.ble_scan = settings.ble_scan
        self.modem_gps_on = settings.modem_gps
        self.gps_addr = settings.modem_gps_addr
        self.obd= settings.obd
        self.obd_addr=settings.obd_addr
        self.modem_gps_client=None
        self.obd_client=None

        self.mqtt_wrapper = MQTTWrapper(
            settings,
            self.logger,
            self._on_mqtt_wrapper_termination_cb,
            self._on_connect
        )

        if self.ble_on :
            # Init BLE
            BLE_Data.registerDataServices()
            # print("Creating BLE Service")
            try:
                self.ble_service = BLE_Client.BLE_Service()
            except BLE_Client.BLE_ServiceException as err:
                self.logger.critical("Error during BLE Service creation => gateway not operational")
                self._ble_on=False
            # print("BLE service created")
            if self.ble_on :
                self.ble_service.setCallbacks(self)

                # Default configuration
                if self.ble_filters is not None :
                    if len(self.ble_filters) > 0:
                        self.logger.info("apply default filters configuration : " + self.ble_filters)
                        self._filter_cmd_procesing(self.ble_filters)

                if self.ble_scan is not None:
                    if len(self.ble_scan) > 0:
                        self.logger.info("apply default scan configuration : " + self.ble_scan)
                        self._scan_cmd_processing(self.ble_scan)

        if self.modem_gps_on :
                self.logger.info("creating the GPS client on:"+self.gps_addr)
                self.modem_gps_client=Modem_GPS_Client.Modem_GPS_GRPC_Client(self.gps_addr,self.logger)
                # test access
                resp=self.modem_gps_client.modem_status()
                if resp == None:
                    self.logger.error("Error attaching GPS service at address:"+self.gps_addr)
                    self.modem_gps_on=False
                    self.modem_gps_client=None
                else:
                    self.logger.info("GPS service client succesfully attached")
        if self.obd :
                 self.obd_client=OBD_Client.OBD_GRPC_Client(self.obd_addr,self.logger)


        # self.first_connection = True
        self.logger.info("Gateway version %s started with id: %s", ble_mqtt_version, self.gw_id)
        self.mqtt_wrapper.start()


    def _on_mqtt_wrapper_termination_cb(self):
        """
        Callback used to be informed when the MQTT wrapper has exited
        It is not a normal situation and better to exit the program
        to have a change to restart from a clean session
        """
        self.logger.error("MQTT wrapper ends. Terminate the program")
        self.exitSem.release()


    def _on_connect(self):
        self.logger.info("MQTT connected!")

        '''
        Changes made following the bug #396
        Subscription is now made after service readiness
        '''
        if self.ble_on :
            # Suscribe topics when the BLE Service is ready
            self.mqtt_wrapper.subscribe("scan/" + self.gw_id, self._scan_cmd_received)
            self.mqtt_wrapper.subscribe("filter/" + self.gw_id, self._filter_cmd_received)
            self.mqtt_wrapper.subscribe("gatt/" + self.gw_id + "/+", self._gatt_cmd_received)
        if self.modem_gps_on :
            self.mqtt_wrapper.subscribe("gps/" + self.gw_id,self._gps_cmd_received)
            self.mqtt_wrapper.subscribe("modem/" + self.gw_id,self._modem_cmd_received)
        if self.obd :
            self.mqtt_wrapper.subscribe("vehicle/" + self.gw_id,self._obd_cmd_received)

        self.mqtt_wrapper.subscribe("solidsense/"+self.gw_id,self._solidsense_cmd_received)

        self.logger.info("******* SolidSense gateway ready *********")
        self.publishGatewayStatus()


    def deferred_thread(fn):
        """
        Decorator to handle a request on its own Thread
        to avoid blocking the calling Thread on I/O.
        It creates a new Thread but it shouldn't impact the performances
        as requests are not supposed to be really frequent (few per seconds)
        """

        def wrapper(*args, **kwargs):
            thread = Thread(target=fn, args=args, kwargs=kwargs)
            thread.start()
            return thread

        return wrapper


    def catchall(fn):
        """
        Decorator to catch all the errors comming from the callback to protect the calling thread
        """

        def wrapper(*args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Exception as e:
                _logger.exception(" Uncaught exception -> ")

        return wrapper


    def run(self):
        # Nothing to do on the main thread - Just wait the end of the MQTT connection
        self.exitSem.acquire()



    def _checkBadParams(self, payload, typeArgs, mandatoryArgs):
        for param in payload:
            if not param in typeArgs:
                self.logger.info("bad param, not in list :" + param)
                return True

            pType, pValues = typeArgs[param]
            aVal = payload[param]

            if not isinstance(aVal, pType):
                self.logger.info("bad type for " + str(aVal))
                return True

            if not (pValues is None or aVal in pValues):
                self.logger.info("bad value for " + str(aVal))
                return True


        for param in mandatoryArgs:
            if param not in payload:
                self.logger.info("param is missing " + param)
                return True

        return False

    ####################################################################
    # BLE Callbacks
    def publishAdvertisement(self,dev,sub_topic,payload):
        topic="advertisement/"+self.gw_id+"/"+str(dev.address())
        if sub_topic != None :
            topic += "/"+sub_topic
        self.mqtt_wrapper.publish(topic,json.dumps(payload))

    def advertisementCallback(self, dev):
        self.logger.info("Advertisement Callback received for:" + str(dev.name()))


        if self.sub_topics :
        # Print debug informations
            sub_topic=None
            out={}
            if dev.isEddystone() :
                #data=dev.EddystoneFrame()
                dev.eddystoneDict(out)
                self.logger.info("Eddystone beacon:" + str(out))
                sub_topic="eddystone"
                self.publishAdvertisement(dev,sub_topic,out)
            elif dev.isiBeacon():
                dev.iBeaconDict(out)
                self.logger.info("IBeacon UUID:" + str(out))
                sub_topic="ibeacon"
                self.publishAdvertisement(dev,sub_topic,out)
            else:
                sdl = dev.getServiceData()
                if sdl != None :
                    # print("Subtopic publish nb:",len(sdl))
                    for sd in sdl :
                        out.clear()
                        sub_topic=sd.name()
                        out['timestamp'] = dev.getAdvTS()
                        out['type']=sd.type()
                        out['value']=sd.value()
                        self.publishAdvertisement(dev,sub_topic,out)



        out = {}

        if self.scanAdv == 'min':
            dev.minDict(out)
        elif self.scanAdv == 'full':
            dev.fullDict(out)
        else:
            return
        self.logger.debug(out)
        # send Data
        self.publishAdvertisement(dev,None,out)


    def scanEndCallback(self, service):
        self.logger.info("Scan finished")
        out = {}

        if self.scanResult == 'summary':
            service.summaryDict(out)
        elif self.scanResult == 'devices':
            service.summaryDict(out)
            service.devicesDict(out)
        else:
            return

        if self.add_gps != None and self.gps_on :
            # let's read the GPS
            resp=self.gps_client.gpsVector()
            out['gps']=resp

        # Print debug informations
        self.logger.debug(out)

        # send Data
        self.mqtt_wrapper.publish("scan_result/"+self.gw_id, json.dumps(out))

    def notificationCallback(self,notification):
        out={}
        notification.fillDict(out)
        self.logger.debug(out)
        self.mqtt_wrapper.publish("gatt_result/"+self.gw_id+"/"+notification.addr(),json.dumps(out))

    ####################################################################
    # Topic processing
    @staticmethod
    def addrFromTopic(topic):
        """
        extract the address of the device that shall be the last in the topic chain
        """
        elem=topic.split('/')
        last=len(elem)-1
        addr=elem[last]
        # check consistency
        if len(addr) != 17 :   # 6x2 Hex digits + 5 colon
            return None
        # further tests to be implemented
        return addr.lower()



    ####################################################################
    # MQTT Callbacks
    def _scan_cmd_received(self, client, userdata, message):
        payload = message.payload.decode("utf-8")
        self.logger.info("scan request : " + payload)
        self._scan_cmd_processing(payload)

    def _filter_cmd_received(self, client, userdata, message):
        payload = message.payload.decode("utf-8")
        self.logger.info("filter request : " + payload)
        self._filter_cmd_procesing(payload)

    def _gatt_cmd_received(self, client, userdata, message):
        payload = message.payload.decode("utf-8")
        self.logger.info("gatt request : " + message.topic+" : "+payload)
        self._gatt_cmd_processing(message.topic,payload)

    def _gps_cmd_received(self,client, userdata, message) :
        payload = message.payload.decode("utf-8")
        self.logger.info("gps request : " + message.topic+" : "+payload)
        self._gps_cmd_processing(message.topic,payload)

    def _modem_cmd_received(self,client, userdata, message) :
        payload = message.payload.decode("utf-8")
        self.logger.info("modem request : " + message.topic+" : "+payload)
        self._modem_cmd_processing(message.topic,payload)

    def _solidsense_cmd_received(self,client, userdata, message) :
        payload = message.payload.decode("utf-8")
        self.logger.info("solidsense request : " + message.topic+" : "+payload)
        self._solidsense_cmd_processing(message.topic,payload)

    ####################################################################
    # JSON Processing

    @catchall
    def _scan_cmd_processing(self, message):
        try:
            payload = json.loads(message)

        except ValueError as e:
            self.logger.error("Bad scan request ->" + str(e))
            return

        typeArgs = {
            'command' : (str, ['start', 'stop', 'time_scan']),
            'timeout' : ((float, int), None),
            'period'  : ((float, int), None),
            'result'  : (str, ['none', 'summary', 'devices']),
            'advertisement'  : (str, ['none', 'min', 'full']),
            'sub_topics'  : (bool, None),
            'adv_interval'  : ((float, int), None),
            'gps' : (str,['position'])
        }

        mandatoryArgs = [
            'command',
        ]

        # Check parameters validity
        if self._checkBadParams(payload, typeArgs, mandatoryArgs):
            self.logger.error("Abort scan request")
            return

        # Check also that data_service is an array of string
        if isinstance(payload.get('data_service', None), list):
            for item in payload['data_service']:
                if not isinstance(item, str):
                    self.logger.error("Abort scan request - data_service is not a list of string")

        # Set parameters
        self.setReportingInterval(payload.get('adv_interval', 0))
        self.scanResult = payload.get('result', 'summary')
        self.scanAdv = payload.get('advertisement', 'min')
        scanTimeout = payload.get('timeout', 10.0)
        period = payload.get('period',0)
        self.sub_topics= payload.get('sub_topics',False)
        self.add_gps=payload.get('gps',None)


        # Execute the commmand
        scanCmd = payload['command']
        if scanCmd == 'time_scan':
            if period == 0 :
                self.ble_service.scanAsynch(scanTimeout, True)
            else:
                self.ble_service.startPeriodicScan(scanTimeout,period)
        elif scanCmd == 'start':
            self.ble_service.startScan(True)
        elif scanCmd == "stop":
            self.ble_service.stopScan()


    @catchall
    def _filter_cmd_procesing(self, message):
        try:
            payload = json.loads(message)

        except ValueError as e:
            self.logger.error("Bad Filter request ->" + str(e))
            return

        typeArgs = {
            'type' : (str, ['rssi', 'white_list', 'connectable', 'starts_with', 'mfg_id_eq', 'none']),
            'min_rssi' : (int, None),
            'match_string' : (str, None),
            'addresses'  : (list, None),
            'connectable_flag' : (bool, [True, False]),
            'mfg_id'  : (int, None),
        }

        mandatoryArgs = [
            'type',
        ]

        requiredArgs = {
            'rssi' : 'min_rssi',
            'white_list' : 'addresses',
            'connectable' : 'connectable_flag',
            'starts_with' : 'match_string',
            'mfg_id_eq' : 'mfg_id',
        }

        # Check parameters validity
        if isinstance(payload, list):
            for payloadItem in payload:
                self.logger.info("check filter : " + str(payloadItem))
                if self._checkBadParams(payloadItem, typeArgs, mandatoryArgs):
                    self.logger.error("Abort Filter request")
                    return
                elif payloadItem['type'] == 'none' :
                    break
                elif payloadItem.get(requiredArgs[payloadItem['type']], None) is None:
                    self.logger.error("Abort Filter request : missing parameter " + requiredArgs[payloadItem['type']])
                    return
        else:
            self.logger.error("Abort Filter request: request is not a list!")
            return

        # Create Filters and add them to the service
        self.ble_service.clearFilters()

        for payloadItem in payload:
            filterType = payloadItem['type']
            if filterType == 'rssi':
                filter = BLE_Client.BLE_Filter_RSSI(payloadItem['min_rssi'])
            elif filterType == 'white_list':
                filter = BLE_Client.BLE_Filter_Whitelist(payloadItem['addresses'])
            elif filterType == 'connectable':
                filter = BLE_Client.BLE_Filter_Connectable(payloadItem['connectable_flag'])
            elif filterType == 'starts_with':
                filter = BLE_Client.BLE_Filter_NameStart(payloadItem['match_string'])
            elif filterType == 'mfg_id_eq':
                filter = BLE_Client.BLE_Filter_MfgID(payloadItem['mfg_id'])
            elif filterType == 'none':
                break

            self.ble_service.addFilter(filter)


    @catchall
    def _gatt_cmd_processing(self,topic,message):

        try:
            payload = json.loads(message)

        except ValueError as e:
            self.logger.error("Bad GATT request ->" + str(e))
            return

        typeArgs = {
            'command' : (str, ['read', 'write', 'discover','allow_notifications']),
            'transac_id' : ( int, None),
            'bond'  : (bool, None),
            'keep'  : (float, None),
            'characteristic'  : (str, None),
            'service': (str,None),
            'properties': (bool, None),
            'type'  : (int, None),
            'value'  : ((float, int, str), None),
            'action_set' : (list,None)
        }

        mandatoryArgs = [
            'command',
        ]

        # print ("topic:",topic)
        # Check parameters validity
        if self._checkBadParams(payload, typeArgs, mandatoryArgs):
            self.logger.error("Abort GATT request")
            return
        addr=SolidSenseMQTTService.addrFromTopic(topic)
        if addr == None :
            self.logger.error("Abort GATT request - invalid address")
            return

        gattCmd=payload['command']
        transac_id=payload.get('transac_id',None)
        keep=payload.get('keep',0.0)
        service=payload.get('service',None)
        out=None
        error=0
        if gattCmd == 'discover' :
            properties=payload.get('properties',False)
            out={}
            dev=self.ble_service.devGATTDiscover(addr, keep, service,out,properties)
            if dev == None :
                self.logger.error("GATT Discovery error on:" + addr)
                error = 3

        else:
            action_set=payload.get('action_set',None)
            actions=[]
            # self.logger.info("GATT "+gattCmd+" Request on device:"+addr)
            if action_set == None :
                action_a = self.buildAction(payload)
                if action_a != None :
                    actions.append(action_a)

            else:
                for action in action_set :
                    action_a = self.buildAction(action)
                    if action_a != None :
                        actions.append(action_a)

            if error == 0 and len(actions) > 0:
                # yes we have something to do
                out={}
                if gattCmd == 'read' :
                    error = self.cmdGATTread(addr,actions,keep,out)
                elif gattCmd == 'write':
                    error=self.cmdGATTwrite(addr,actions,keep,out)
                elif gattCmd == 'allow_notifications':
                    error=self.cmdGATTallowNotifications(addr,actions,keep,out)

        result=self.buildGATTresponse(gattCmd,error,transac_id,out)
        self.logger.debug("Publish GATT request result:"+result)
        self.mqtt_wrapper.publish("gatt_result/"+self.gw_id+"/"+addr,result)


    def buildAction(self,pd):
        res=[]
        c=pd.get('characteristic',None)
        if c == None : return None
        res.append(c)
        res.append(pd.get('type',BLE_Data.BLE_DataService.BTRAW))
        v= pd.get('value',None)
        if v != None :
            res.append(v)
        return res

    def cmdGATTread(self,addr,actions,keep,out):
        self.logger.debug("GATT read on:"+addr+" #actions:"+str(len(actions)))
        try:
            return self.ble_service.readCharacteristics(addr,actions,keep,out)
        except BLE_Client.BLE_ServiceException as err:
            return 4

    def cmdGATTwrite(self,addr,actions,keep,out):
        self.logger.debug("GATT write on:"+addr+" #actions:"+str(len(actions)))
        try:
            return self.ble_service.writeCharacteristics(addr,actions,keep,out)
        except BLE_Client.BLE_ServiceException as err:
            return 4

    def cmdGATTallowNotifications(self,addr,actions,keep,out) :
        self.logger.debug("GATT allow notifications on:"+addr+" #actions:"+str(len(actions)))
        try:
            return self.ble_service.allowNotifications(addr,actions,keep,out)
        except BLE_Client.BLE_ServiceException as err:
            return 4


    def buildGATTresponse(self, command,  error, transac_id, result):
        out = {}
        out['command'] = command
        out['error'] = error
        if transac_id is not None :
            out['transac_id']=transac_id

        if error == 0 and result != None:
            out['result'] = result

        return json.dumps(out)

####################################################################
#   Modem and GPS commands
#
    def gpsPositionCallback(self,gps_position):
        payload=self.buildGPSresponse('position',0,gps_position)
        self.logger.debug("Publish GPS position"+str(gps_position))
        self.mqtt_wrapper.publish('gps_result/'+self.gw_id,payload)

    def modemStatusCallback(self,modem_status):
        payload=self.buildGPSresponse('status',0,modem_status)
        self.logger.debug("Publish Modem status "+str(modem_status))
        self.mqtt_wrapper.publish('modem_result/'+self.gw_id,payload)

    @catchall
    def _gps_cmd_processing(self, topic, message) :


        try:
            payload = json.loads(message)

        except ValueError as e:
            self.logger.error("Bad GPS request ->" + str(e))
            return

        typeArgs = {
            'command' : (str, ['read', 'start', 'stop','status']),
            'period' : ( float, None),
            'distance'  : (float, None)
        }

        mandatoryArgs = [
            'command'
        ]
        if not self.modem_gps_on :
            # no need to do anything but reply an error
            resp=self.buildGPSresponse("gps",1,"No GPS")
            self.mqtt_wrapper.publish("gps_result/"+self.gw_id,resp)
            return

        # print ("topic:",topic)
        # Check parameters validity
        if self._checkBadParams(payload, typeArgs, mandatoryArgs):
            self.logger.error("Abort GPS request")
            return

        command=payload['command']
        error=0
        resp=None
        if command == "status":
            resp=self.gps_client.gps_status()
            if resp == None : error =3
        elif command == "read" :
            resp=self.gps_client.gpsVector()
            if resp == None : error =3
        elif command == "start":
            period=payload.get('period',60.)
            self.modem_gps_client.startGPSPeriodicRead(period,self.gpsPositionCallback)
        elif command == "stop" :
            self.modem_gps_client.stopGPSPeriodicRead()

        if resp != None or error != 0:
           r_payload=self.buildGPSresponse(command,error,resp)
           self.logger.debug("Publish GPS response to "+command+" error="+str(error))
           self.mqtt_wrapper.publish('gps_result/'+self.gw_id,r_payload)


    def buildGPSresponse(self,command,error,result):
        out = {}
        out['command'] = command
        out['error'] = error
        out['timestamp'] = MQTT_Timestamp.now()

        if error == 0 and result != None:
            out['result'] = result

        return json.dumps(out)

    def _modem_cmd_processing(self,topic,message):

        try:
            payload = json.loads(message)

        except ValueError as e:
            self.logger.error("Bad modem request ->" + str(e))
            return

        typeArgs = {
            'command' : (str, ['operators', 'status','stop']),
            'period' : ( float, None)
        }

        mandatoryArgs = [
            'command'
        ]
        if not self.modem_gps_on :
            # no need to do anything but reply an error
            resp=self.buildGPSresponse("modem",1,"No Modem")
            self.mqtt_wrapper.publish("modem_result/"+self.gw_id,resp)
            return

        if payload['command'] == 'status' :

            resp=self.modem_gps_client.modem_status()
            self.modemStatusCallback(resp)
            period= payload.get('period',0.0)
            if  period > 0.0 :
                self.modem_gps_client.startModemPeriodicRead(period,self.modemStatusCallback)

        elif  payload['command'] == 'stop' :
             self.modem_gps_client.stopModemPeriodicRead()


    # global gateway function
    def publishGatewayStatus(self):
        out={}
        serv=[]
        serv.append(('ble',self.ble_on))
        serv.append(('modem_gps',self.modem_gps_on))
        serv.append(('vehicle',self.obd))
        out['timestamp']=MQTT_Timestamp.now()
        out['status']=serv
        self.logger.debug("Publish global gateway status")
        self.mqtt_wrapper.publish('solidsense_resp/'+self.gw_id,json.dumps(out))



####################################################################
# Main function & arguments parsing

class SolidSenseParserHelper(ParserHelper):
    def __init__(
            self,
            description="argument parser",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            version=None,
        ):

        super().__init__(description, formatter_class, version)

    def init_config(self):
        self.add_file_settings()
        self.add_mqtt()
        self.add_gateway_config()
        self.add_ble_config()
        self.add_ms_config()


    def add_ble_config(self):
        self.ble.add_argument (
            "--ble",
            default=False,
            action="store_true",
            help=("True if a BLE scanner/GATT client to be attached to the MQTT client")
        )

        self.ble.add_argument(
            "--ble_filters",
            default=None,
            help=("The list of filters that will be enabled at the service startup, in the JSON format"),
        )

        self.ble.add_argument(
            "--ble_scan",
            default=None,
            help=("The scan command that will be executed at the service startup, in the JSON format"),
        )

    def add_ms_config(self):
        # configuration of micro service
        # GPS
        self.ms.add_argument(
            "--modem_gps",
            default=False,
            action="store_true",
            help=("True if a Modem/GPS is to be attached to the MQTT client")
        )
        self.ms.add_argument(
            "--modem_gps_addr",
            default="127.0.0.1:20231",
            action="store",
            type=str,
            help=("Address and port of the gps micro service if not the default one")
        )
        # OBD
        self.ms.add_argument(
            "--obd",
            default=False,
            action="store_true",
            help=("True if a OBD is to be attached to the MQTT client")
        )
        self.ms.add_argument(
            "--obd_addr",
            default="127.0.0.1:20232",
            action="store",
            type=str,
            help=("Address and port of the OBD micro service if not the default one")
        )


def _check_parameters(settings, logger):
    if settings.mqtt_force_unsecure and settings.mqtt_certfile:
        # If tls cert file is provided, unsecure authentication cannot
        # be set
        logger.error("Cannot give certfile and disable secure authentication")
        exit()



def main():
    """
        Main service for transport module

    """

    global _logger

    parse = SolidSenseParserHelper(
        description="BLE Transport service arguments",
    )
    parse.init_config()

    settings = parse.settings()
    if settings.gateway_id is None:
        settings.gateway_id = socket.gethostname()



    log = LoggerHelper(module_name="BLEService", level='error')
    _logger = log.setup()
    BLE_Client.BLE_init_parameters()
    # Set debug level
    _logger.setLevel(logging.DEBUG)
    # Override BLE_CLient logger to get logs with the same format
    BLE_Client.blelog = _logger

    _check_parameters(settings, _logger)

    try:
        SolidSenseMQTTService(settings=settings, logger=_logger).run()
    except ConnectionRefusedError as cre:
        _logger.error("Connection refused, try later...")
    except Exception as e:
        _logger.exception(" Uncaught exception (Main Thread) -> ")


if __name__ == "__main__":
    main()

#-------------------------------------------------------------------------------
# Name:        GPS_Clent
# Purpose:  Encpasulate rRPC interface to GPS service
#
# Author:      Laurent Carré
#
# Created:     15/03/2020
# Copyright:   (c) Laurent Carré Sterwen Technologies 2020
# Licence:     <your licence>
#-------------------------------------------------------------------------------

import os
import sys
import inspect

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../Modem_GPS_Service")))
sys.path.insert(0, cmd_subfolder)

import threading
import logging
import time
import grpc
from GPS_Service_pb2 import *
import GPS_Service_pb2_grpc


class Modem_GPS_GRPC_Client() :

    s_attr=('fix','timestamp','nbsat','date','hdop')
    v_attr=('fix','timestamp','latitude','longitude','SOG','COG')
    mf_attr=('model','IMEI','IMSI','ICCID','network_reg','PLMNID','network_name','rat','band','lac','ci','rssi')
    ms_attr=('network_reg','PLMNID','network_name','rat','band','lac','ci','rssi')

    def __init__(self,addr,logger) :

        self._logger=logger
        self._logger.debug("Modem GPS creating gRPC channel on:"+addr)
        self._channel= grpc.insecure_channel(addr)
        self._stub= GPS_Service_pb2_grpc.GPS_ServiceStub(self._channel)
        self._gps_running=False
        self._modem_running=False



    def modem_status(self):

        req=ModemCmd(command='status')
        try:
            resp=self._stub.modemCommand(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        self._logger.debug("Read modem status result "+resp.response)
        if resp.response == 'OK':
            out=Modem_GPS_GRPC_Client.GpsMsg_ToDict(resp.status,Modem_GPS_GRPC_Client.mf_attr)
            return out
        else:
            return None

    def gps_status(self):
        req=PositionSpec(spec=PositionSpec.P2D)
        try:
            resp=self._stub.getPrecision(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        out=Modem_GPS_GRPC_Client.GpsMsg_ToDict(resp,Modem_GPS_GRPC_Client.s_attr)
        if resp.nbsat > 0:
            sat_num=[]
            for n in resp.sat_num :
                sat_num.append(n)
            out['sat_num']=sat_num
        return out

    def gpsVector(self):
        req=PositionSpec(spec=PositionSpec.P2D)
        try:
            resp=self._stub.getVector(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        if resp.fix:
            out= Modem_GPS_GRPC_Client.GpsMsg_ToDict(resp,Modem_GPS_GRPC_Client.v_attr)
        else:
            out={"fix":False}
        return out

    def startGPSPeriodicRead(self,period,callback):
        self._gps_period=period
        if not self._gps_running :
            self._gps_running=True
            self._gps_callback=callback
            self.readGpsAndCallback()

    def startModemPeriodicRead(self,period,callback):
        self._modem_period=period
        if not self._modem_running :
            self._modem_running = True
            self._modem_callback=callback
            self.armModemTimer()


    def stopGPSPeriodicRead(self):
        self._gps_running=False

    def stopModemPeriodicRead(self):
        self._modem_running = False

    def armGPSTimer(self):
        self._gps_timer=threading.Timer(self._gps_period,self.readGpsAndCallback)
        self._gps_timer.start()

    def armModemTimer(self):
        self._modem_timer=threading.Timer(self._modem_period,self.readModemAndCallback)
        self._modem_timer.start()

    def readModemAndCallback(self):
        req=ModemCmd(command='status')
        try:
            resp=self._stub.modemCommand(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            self._modem_running=False
            return
        if resp.response == 'OK' :
           out=Modem_GPS_GRPC_Client.GpsMsg_ToDict(resp.status,Modem_GPS_GRPC_Client.ms_attr)
           self._modem_callback(out)
        if self._modem_running :
            self.armModemTimer()

    def readGpsAndCallback(self):
        resp=self.gpsVector()
        if resp==None :
            self._gps_running = False
            return
        self._logger.debug("GPS Periodic read result "+str(resp) )
        self._gps_callback(resp)
        if self._gps_running :
            self.armGPSTimer()


    @staticmethod
    def GpsMsg_ToDict(msg,attribs):
        out={}
        for attr in attribs:
            try:
                val=getattr(msg,attr)
                out[attr]=val
            except AttributeError :
                 print("Modem GPS service missing field:"+attr)
                 out[attr]=None
        return out



class T():

    def printGPS(self,resp) :
        if resp.fix :
            print("LAT:",resp.latitude,"LONG:",resp.longitude,"SOG:",resp.SOG,"COG:",resp.COG)
        else:
            print("No fix")


def main():

    logger= logging.getLogger('Test-GPS')
    logging.basicConfig()
    logger.setLevel(logging.DEBUG)
    gps=GPS_GRPC_Client("127.0.0.1:20231",logger)
    resp=gps.modem_status()
    if resp == None : return
    if resp.response == "OK" and  resp.status.gps_on == True :
        v= gps.gps_status()
        print (v )
    '''
        if v.fix == True:
            print("LAT:",v.latitude,"LONG:",v.longitude,"SOG:",v.SOG,"COG:",v.COG)
        else:
            print("GPS not fixed")
    # test periodic reading
    t=T()
    gps.startPeriodicRead(10.,t.printGPS)
    time.sleep(30.)
    gps.stopPeriodicRead()
    time.sleep(15.)
    '''


if __name__ == '__main__':
    main()

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

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../modem_gps")))
sys.path.insert(0, cmd_subfolder)

import threading
import logging
import time
import json
import grpc
from GPS_Service_pb2 import *
import GPS_Service_pb2_grpc


class Modem_GPS_GRPC_Client() :

    s_attr=('fix','gps_time','nbsat','date','hdop')
    v_attr=('fix','gps_time','latitude','longitude','altitude','SOG','COG')
    mf_attr=('model','IMEI','IMSI','ICCID','network_reg','PLMNID','network_name','rat','band','lac','ci','rssi')
    ms_attr=('network_reg','PLMNID','network_name','rat','band','lac','ci','rssi')
    mo_attr=('model','IMEI','IMSI','ICCID','network_reg','PLMNID','network_name','rat','band','lac','ci','rssi','operators')

    def __init__(self,addr,logger) :

        self._logger=logger
        self._logger.debug("Modem GPS creating gRPC channel on:"+addr)
        self._channel= grpc.insecure_channel(addr)
        self._stub= GPS_Service_pb2_grpc.GPS_ServiceStub(self._channel)
        self._gps_running=False
        self._modem_running=False
        self._streamer=None



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

    def modem_operators(self):
        req=ModemCmd(command='operator')
        try:
            resp=self._stub.modemCommand(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        self._logger.debug("Read modem status result "+resp.response)
        if resp.response == 'OK':
            out=Modem_GPS_GRPC_Client.GpsMsg_ToDict(resp.status,Modem_GPS_GRPC_Client.mo_attr)
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

    def stopGPS(self):
        if self._streamer != None :
            self.stopGPSStreaming()
        else:
            self.stopGPSPeriodicRead()

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
            # error here we shall not stop the periodic reading
            # self._modem_running=False
            # return
        else:
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

    def startGPSStreaming(self,callback,end_callback,rules):
        rules_j=json.dumps(rules)
        self._streamer=ContinuousGPSReader(self,callback,end_callback,self._logger,rules_j)
        self._streamer.start()

    def stopGPSStreaming(self):
        req=ModemCmd()
        req.command="STOP"
        resp=self._stub.stopStream(req)
        self._logger.debug("Stop streaming acknowledgement:"+resp.response)

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


class ContinuousGPSReader(threading.Thread):
    '''
    this class is used to read a continuous stream of gps event
    and throwing a call for each of them
    '''
    def __init__(self,client,callback,end_callback,logger,rules):
        threading.Thread.__init__(self)
        self._client=client
        self._callback=callback
        self._end_callback=end_callback
        self._logger=logger
        self._rules=rules

    def run(self):
        req=ModemCmd()
        req.command=self._rules
        error=None
        try:
            for pos in self._client._stub.streamGPS(req) :
                if pos.fix:
                    resp=Modem_GPS_GRPC_Client.GpsMsg_ToDict(pos,Modem_GPS_GRPC_Client.v_attr)
                else:
                    resp={}
                    resp['fix']=False
                self._callback(resp)
        except Exception as err:
            self._logger.error("Error in GPS streaming:"+str(err))
            error=err
            pass

        self._client._streamer=None
        self._logger.info("End GPS streaming")
        self._end_callback(error)
        # self._logger.info("After end callback")




class T():

    def printGPS(self,resp) :
        if resp.fix :
            print("LAT:",resp.latitude,"LONG:",resp.longitude,"SOG:",resp.SOG,"COG:",resp.COG)
        else:
            print("No fix")


def pos_callback(pos):
    print("Callback:",pos)

def main():

    logger= logging.getLogger('Test-GPS')
    logging.basicConfig()
    logger.setLevel(logging.DEBUG)
    gps=Modem_GPS_GRPC_Client("127.0.0.1:20231",logger)
    resp=gps.modem_status()
    if resp == None : return

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
    rules={"fixtime":10,"no_fix_time":60,"distance":100}
    gps.startGPSStreaming(pos_callback,rules)
    time.sleep(60.)
    gps.stopGPSStreaming()


if __name__ == '__main__':
    main()

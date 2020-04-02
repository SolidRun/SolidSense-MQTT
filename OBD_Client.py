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

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../../OBD")))
sys.path.insert(0, cmd_subfolder)

import threading
import logging
import time
import grpc


class OBD_GRPC_Client() :

    def __init__(self,addr,logger) :

        self._logger=logger
        self._logger.debug("creating grpc channel on:"+addr)
        self._channel= grpc.insecure_channel(addr)
        self._stub= GPS_Service_pb2_grpc.GPS_ServiceStub(self._channel)





    def startPeriodicRead(self,period,callback):
        self._period=period
        self._running=True
        self._callback=callback
        self.readGpsAndCallback()

    def stopPeriodicRead(self):
        self._running=False

    def armTimer(self):
        a=[self]
        self._timer=threading.Timer(self._period,self.readGpsAndCallback)
        self._timer.start()

    def readGpsAndCallback(self):
        resp=self.gpsVector()
        if resp==None :
            self._running = False
            return
        self._logger.debug("GPS Periodic read result "+str(resp.fix) )
        self._callback(resp)
        if self._running :
            self.armTimer()




def main():
    pass

if __name__ == '__main__':
    main()

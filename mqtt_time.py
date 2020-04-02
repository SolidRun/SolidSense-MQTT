#-------------------------------------------------------------------------------
# Name:        MQTTTimestamp
# Purpose:
#
# Author:      Laurent Carré
#
# Created:     30/03/2020
# Copyright:   (c) Laurent Carré Sterwen Technologies 2020
# Licence:     <your licence>
#-------------------------------------------------------------------------------

import time
import datetime



class MQTT_Timestamp:

    ts_format='iso'

    def __init__(self):
        pass

    @staticmethod
    def setFormat(ts_format):
        MQTT_Timestamp.ts_format=ts_format

    @staticmethod
    def now():

        return MQTT_Timestamp.format_ts(datetime.datetime.now())

    @staticmethod
    def fromEpoch(epoch):
        t=datetime.datetime.fromtimestamp(epoch)
        return MQTT_Timestamp.format_ts(t)

    @staticmethod
    def format_ts(ts):
        if MQTT_Timestamp.ts_format == 'iso' :
            return ts.isoformat(' ')







def main():
    pass

if __name__ == '__main__':
    main()

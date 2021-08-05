#!/usr/bin/env python

'''
Apartment Door Buzzer System
Capture calls from APARTMENT to TWILIO, initiate conference, and patch in TENANT1 and TENANT2

@author: sbrown
'''

VERSION = "5.0"
DATE = "July 31, 2021"


## Import Libraries

from flask import Flask, request, redirect, abort
from twilio.twiml.voice_response import VoiceResponse, Gather, Dial
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from functools import wraps
import time
from phue import Bridge
import threading
import ssl
import configparser

config = configparser.ConfigParser()
config.read('config.ini')

context = ssl.SSLContext()
context.load_cert_chain(config.get("SSL","letsencrypt_fullchain"), config.get("SSL","letsencrypt_privkey"))

bridge = Bridge(config.get("Hue","hue_bridge_ip"))

account_sid = config.get("Twilio","account_sid")
auth_token = config.get("Twilio","auth_token")
client = Client(account_sid, auth_token)

IP_ADDR = config.get("Server","url")
RING_URL = config.get("Server","ring_sound")

TWILIO = config.get("PhoneNumbers","TWILIO")
APARTMENT = config.get("PhoneNumbers","APARTMENT")
TENANT1 = config.get("PhoneNumbers","TENANT1")
TENANT2 = config.get("PhoneNumbers","TENANT2")

LOG_FILE = "buzzerSystemOutput.log"
lf = open(LOG_FILE, "w")
lf.close()

TENANT1_call = ""
TENANT2_call = ""

app = Flask(__name__)

def log_print(msg):
    logfh = open(LOG_FILE, "a")
    logfh.write("[{}]: {}\n".format(time.strftime("%Y/%m/%d %T"), msg))
    print("[{}]: {}\n".format(time.strftime("%Y/%m/%d %T"), msg))
    logfh.close()

def flash_light_1():
    flash_color_light(int(config.get("Hue","light_1")))

def flash_light_2():
    flash_light(int(config.get("Hue","light_2")))

def flash_light_3():
    flash_light(int(config.get("Hue","light_3")))


def flash_color_light(L):
    onoff = bridge.get_light(L, "on")
    bhue = bridge.get_light(L, "hue")
    bsat = bridge.get_light(L, "sat")
    bbri = bridge.get_light(L, "bri")

    blue = {'on':True, 'bri':254, 'sat':254, 'hue':45455}
    red = {'on':True, 'bri':254, 'sat':254, 'hue':65359}
    pause = 0.25

    for i in range(0,5):
        bridge.set_light(L, blue)
        time.sleep(pause)
        bridge.set_light(L, red)
        time.sleep(pause)

    bridge.set_light(L, {"on":onoff, "hue":bhue, "sat":bsat, "bri":bbri})

def flash_light(L):
    onoff = bridge.get_light(L, "on")
    bbri = bridge.get_light(L, "bri")

    on = {'on':True, 'bri':254}
    off = {'on':False}
    pause = 0.25

    for i in range(0,5):
        bridge.set_light(L, on)
        time.sleep(pause)
        bridge.set_light(L, off)
        time.sleep(pause)

    if onoff:
        ## Light was on, set brightness too.
        bridge.set_light(L, {"on":onoff, "bri":bbri})
    else:
        ## light was off, just set to off
        bridge.set_light(L, "on", onoff)


def validate_twilio_request(f):
    """Validates that incoming requests genuinely originated from Twilio"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        log_print("Validating request originated from Twilio...")
        # Create an instance of the RequestValidator class
        validator = RequestValidator(auth_token)

        # Validate the request using its URL, POST data,
        # and X-TWILIO-SIGNATURE header
        log_print("Validating url: {}, form: {}, header: {}".format(request.url, request.form, request.headers.get("X-TWILIO-SIGNATURE", "")))
        log_print("Validating url: {}, form: {}, header: {}".format(request.url, request.form, request.headers.get("X-TWILIO-SIGNATURE", "")))
        request_valid = validator.validate(
            request.url,
            request.form,
            request.headers.get('X-TWILIO-SIGNATURE', ''))
        log_print(request_valid)
        

        # Continue processing the request if it's valid, return a 403 error if
        # it's not
        if request_valid:
            log_print("Approved.")
            return f(*args, **kwargs)
        else:
            log_print("Invalid - blocked.")
            return abort(403)
    return decorated_function



@app.route("/", methods=["GET","POST"])
@validate_twilio_request
def call():
    """Responds to incoming call"""

    global TENANT1_call
    global TENANT2_call

    resp = VoiceResponse()

    dial = Dial()
    log_print("Handling call initiated by: {}".format(request.values.get("From")))

    if request.values.get("From") == TWILIO:
        log_print("This is an outbound call to TENANT1 or TENANT2 - waiting for response...")

        if request.values.get("To") == TENANT1:
            log_print("TENANT1 answered the doorbell.")
            log_print("Ending call to TENANT2.")
            client.calls(TENANT2_call.sid).update(status="completed")
        else:
            log_print("TENANT2 answered the doorbell.")
            log_print("Ending call to TENANT1.")
            client.calls(TENANT1_call.sid).update(status="completed")
        dial = Dial()
        dial.conference("Buzzer conference", start_conference_on_enter=True, end_conference_on_exit=True)

        return str(resp.append(dial))


    elif request.values.get("From") == APARTMENT:
        log_print("Putting call from APARTMENT enterphone into conference.")
        dial.conference("Buzzer conference", start_conference_on_enter=False, end_conference_on_exit=True, wait_url="/hold", wait_method="GET")
        ## initiate outbound calls to TENANT1 and TENANT2, patch in

        log_print("Initiating outbound call to TENANT1.")
        TENANT1_call = client.calls.create(to=TENANT1, from_=TWILIO, url=IP_ADDR)
        log_print("Initiating outbound call to TENANT2.")
        TENANT2_call = client.calls.create(to=TENANT2, from_=TWILIO, url=IP_ADDR)

        return str(resp.append(dial))

    elif request.values.get("From") == None:
        #not a call, a bot connection attempt
        log_print("Fake incoming call: {}".format(request.values.get()))
        return str(resp)

    elif request.values.get("From") == TENANT1:
        # test call from TENANT1
        log_print("Test call from TENANT1")
        resp.say("Hi TENANT1, all seems to be working!")
        dial.conference("Buzzer conference", start_conference_on_enter=False, end_conference_on_exit=True, wait_url="/hold", wait_method="GET")

        t1 = threading.Thread(target=flash_light_1)
        t2 = threading.Thread(target=flash_light_3)
        t3 = threading.Thread(target=flash_light_2)
        t1.start()
        t2.start()
        t3.start()

        return str(resp.append(dial))

    else:
        log_print("Unknown caller to TWILIO.".format(request.values.get("From")))
        log_print("Forwarding to TENANT1.")
        resp.dial(TENANT1)
        return str(resp)

@app.route("/hold", methods=["GET", "POST"])
def hold():
    resp = VoiceResponse()
    #resp.say("Connecting to TENANT1 and TENANT2, one moment please.")
    resp.play(RING_URL)
    ## flashing lights
    t1 = threading.Thread(target=flash_light_1)
    t2 = threading.Thread(target=flash_light_3)
    t3 = threading.Thread(target=flash_light_2)
    t1.start()
    t2.start()
    t3.start()
    return str(resp)



if __name__ == "__main__":

    client.api.account.messages.create(to=TENANT1, from_=TWILIO, body="[{}]: Buzzer System {} has booted successfully.".format(time.strftime("%Y/%m/%d %T"), VERSION))
    app.run(ssl_context=context, host="0.0.0.0", port=config.get("Server","port"))
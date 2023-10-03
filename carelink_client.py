###############################################################################
#  
#  Carelink Client library
#  
#  Description:
#
#    This library implements a client for the Medtronic Carelink API.
#    It is a port of the original Java client by Bence Szász:
#    https://github.com/benceszasz/CareLinkJavaClient
#  
#  Author:
#
#    Ondrej Wisniewski (ondrej.wisniewski *at* gmail.com)
#  
#  Changelog:
#
#    09/05/2021 - Initial public release
#    06/06/2021 - Add check for expired token
#    19/09/2022 - Check for general BLE device family to support 770G
#    09/05/2023 - Fix connection issues by removing common http headers
#    24/05/2023 - Add handling of patient Id in data request
#    29/06/2023 - Get login parameters from response to connection request
#    29/09/2023 - Add recaptcha workaround
#    02/10/2023 - Add refresh of auth token
#
#  Copyright 2021-2023, Ondrej Wisniewski 
#
###############################################################################

import json
import requests
import time
import logging as log
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qsl

# Version string
VERSION = "0.8"

# Constants
CARELINK_CONNECT_SERVER_EU = "carelink.minimed.eu"
CARELINK_CONNECT_SERVER_US = "carelink.minimed.com"
CARELINK_LANGUAGE_EN = "en"
CARELINK_LOCALE_EN = "en"
CARELINK_AUTH_TOKEN_COOKIE_NAME = "auth_tmp_token"
CARELINK_TOKEN_VALIDTO_COOKIE_NAME = "c_token_valid_to"
AUTH_EXPIRE_DEADLINE_MINUTES = 1

# Logging config
FORMAT = '[%(asctime)s:%(levelname)s] %(message)s'
log.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S', level=log.INFO)

DEBUG = False

def printdbg(msg):
   if DEBUG:
      print(msg)


class CareLinkClient(object):
   
   def __init__(self, carelinkUsername, carelinkPassword, carelinkCountry, carelinkPatient):
      
      # User info
      self.__carelinkUsername = carelinkUsername
      self.__carelinkPassword = carelinkPassword
      self.__carelinkCountry = carelinkCountry.lower()
      self.__carelinkPatient = carelinkPatient

      # Session info
      self.__sessionUser = None
      self.__sessionProfile = None
      self.__sessionCountrySettings = None
      self.__sessionMonitorData = None

      # State info
      self.__loginInProcess = False
      self.__loggedIn = False
      self.__lastDataSuccess = False
      self.__lastResponseCode = None
      self.__lastErrorMessage = None

      self.__commonHeaders = {}
      '''
      self.__commonHeaders = {
            # Common browser headers
            "Accept-Language":"en;q=0.9, *;q=0.8",
            "Connection":"keep-alive",
            "sec-ch-ua":"\"Google Chrome\";v=\"87\", \" Not;A Brand\";v=\"99\", \"Chromium\";v=\"87\"",
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
          }
      '''
      # Create main http client session with CookieJar
      self.__httpClient = requests.Session()
    
   
   def getLastDataSuccess(self):
      return self.__lastDataSuccess
    
   
   def getLastResponseCode(self):
      return self.__lastResponseCode
    
   
   def getLastErrorMessage(self):
      return self.__lastErrorMessage
   

   # Get server URL
   def __careLinkServer(self):
      return CARELINK_CONNECT_SERVER_US if self.__carelinkCountry == "us" else CARELINK_CONNECT_SERVER_EU


   def __extractResponseData(self, responseBody, begstr, endstr):
      beg = responseBody.find(begstr) + len(begstr)
      end = responseBody.find(endstr,beg)
      return responseBody[beg:end].strip("\"")
   

   def __getLoginSession(self):
      url = "https://" + self.__careLinkServer() + "/patient/sso/login"
      payload = {"country":self.__carelinkCountry, "lang":CARELINK_LANGUAGE_EN}
      try:
         response = self.__httpClient.get(url, headers = self.__commonHeaders, params = payload)
         if not response.ok:
            raise ValueError("session response is not OK")
         #print(response.url)  # DEBUG
      except Exception as e:
         printdbg(e)
         printdbg("__getLoginSession() failed")
      else:
         printdbg("__getLoginSession() success")
      
      return response 


   def __doLogin(self, loginSessionResponse):
      queryParameters = dict(parse_qsl(urlparse(loginSessionResponse.url).query))
      p = urlparse(loginSessionResponse.url)
      url = p.scheme + "://" + p.netloc + p.path
      payload = { "country":queryParameters["countrycode"], 
                  "locale":queryParameters["locale"]
                }
      form =    { "sessionID":queryParameters["sessionID"],
                  "sessionData":queryParameters["sessionData"],
                  "locale":queryParameters["locale"],
                  "action":"login",
                  "username":self.__carelinkUsername,
                  "password":self.__carelinkPassword,
                  "g-recaptcha-response":"abc", # FIXME
                  "actionButton":"Log in"
                }
      try:
         response = self.__httpClient.post(url, headers = self.__commonHeaders, params = payload, data = form)
         if not response.ok:
            raise ValueError("session response is not OK")
      except Exception as e:
         printdbg(e)
         printdbg("__doLogin() failed")
      else:
         printdbg("__doLogin() success")
      
      return response


   def __doConsent(self, doLoginResponse):
      # Extract data for consent
      doLoginRespBody = doLoginResponse.text
      url         = self.__extractResponseData(doLoginRespBody, "<form action=", " ")
      sessionID   = self.__extractResponseData(doLoginRespBody, "<input type=\"hidden\" name=\"sessionID\" value=", ">")
      sessionData = self.__extractResponseData(doLoginRespBody, "<input type=\"hidden\" name=\"sessionData\" value=", ">")
   
      # Send consent
      form = { "action":"consent",
               "sessionID":sessionID,
               "sessionData":sessionData,
               "response_type":"code",
               "response_mode":"query"
             }   
      # Add header
      consentHeaders = self.__commonHeaders
      consentHeaders["Content-Type"] = "application/x-www-form-urlencoded"
   
      try:
         response = self.__httpClient.post(url, headers = consentHeaders, data = form)
         if not response.ok:
            raise ValueError("session response is not OK")
      except Exception as e:
         printdbg(e)
         printdbg("__doConsent() failed")
      else:
         printdbg("__doConsent() success")
      
      return response 


   def __getData(self, host, path, queryParams, requestBody):
      printdbg("__getData()")
      self.__lastDataSuccess = False;
      if host==None:
         url = path
      else:
         url = "https://" + host + "/" + path
      payload = queryParams
      data = requestBody
      jsondata = None
   
      # Get auth token
      authToken = self.__getAuthorizationToken()

      if (authToken != None):
         try:
            # Add header
            headers = self.__commonHeaders
            headers["Authorization"] = authToken
            if data == None:
               headers["Accept"] = "application/json, text/plain, */*"
               headers["Content-Type"] = "application/json; charset=utf-8"
               response = self.__httpClient.get(url, headers = headers, params = payload)
               self.__lastResponseCode = response.status_code
               if not response.ok:
                  raise ValueError("session get response is not OK")
            else:
               headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
               headers["Content-Type"] = "application/x-www-form-urlencoded"
               response = self.__httpClient.post(url, headers = headers, data = data)
               self.__lastResponseCode = response.status_code
               if not response.ok:
                  printdbg(response.status_code)
                  raise ValueError("session post response is not OK")
         except Exception as e:
            printdbg(e)
            printdbg("__getData() failed")
         else:
            jsondata = json.loads(response.text)
            self.__lastDataSuccess = True

      return jsondata


   def __getMyUser(self):
      printdbg("__getMyUser()")
      return self.__getData(self.__careLinkServer(), "patient/users/me", None, None)


   def __getMyProfile(self):
      printdbg("__getMyProfile()")
      return self.__getData(self.__careLinkServer(), "patient/users/me/profile", None, None)


   def __getCountrySettings(self, country, language):
      printdbg("__getCountrySettings()")
      queryParams = { "countryCode":country,
                      "language":language
                    }
      return self.__getData(self.__careLinkServer(), "patient/countries/settings", queryParams, None)


   def __getMonitorData(self):
      printdbg("__getMonitorData()")
      return self.__getData(self.__careLinkServer(), "patient/monitor/data", None, None,)


   # Old last24hours webapp data
   def __getLast24Hours(self):
      printdbg("__getLast24Hours")
      queryParams = { "cpSerialNumber":"NONE",
                      "msgType":"last24hours",
                      "requestTime":str(int(time.time()*1000))
                    }
      return self.__getData(self.__careLinkServer(), "patient/connect/data", queryParams, None)


   # Periodic data from CareLink Cloud
   def __getConnectDisplayMessage(self, username, role, patient, endpointUrl):
      printdbg("__getConnectDisplayMessage()")
   
      # Build user json for request
      userJson = { "username":username,
                   "role":role,
                   "patientId":patient
                 }
      requestBody = json.dumps(userJson)
      recentData = self.__getData(None, endpointUrl, None, requestBody)
      if recentData != None:
         self.__correctTimeInRecentData(recentData)
      return recentData


   def __correctTimeInRecentData(self,recentData):
      # TODO
      pass


   def __executeLoginProcedure(self):
   
      lastLoginSuccess = False
      self.__loginInProcess = True
      self.__lastErrorMessage = None
      
      log.info("Performing login")

      try:
         # Clear cookies
         self.__httpClient.cookies.clear_session_cookies()

         # Clear basic infos
         self.__sessionUser = None
         self.__sessionProfile = None
         self.__sessionCountrySettings = None
         self.__sessionMonitorData = None

         # Open login (get SessionId and SessionData)
         loginSessionResponse = self.__getLoginSession()
         self.__lastResponseCode = loginSessionResponse.status_code
      
         # Login
         doLoginResponse = self.__doLogin(loginSessionResponse)
         self.__lastResponseCode = doLoginResponse.status_code
         #setLastResponseBody(loginSessionResponse)
         loginSessionResponse.close()
      
         # Consent
         consentResponse = self.__doConsent(doLoginResponse)
         self.__lastResponseCode = consentResponse.status_code
         #setLastResponseBody(consentResponse);
         doLoginResponse.close()
         consentResponse.close()
      
         # Get sessions infos if required
         if self.__sessionUser == None:
            self.__sessionUser = self.__getMyUser()
         if self.__sessionProfile == None:
            self.__sessionProfile = self.__getMyProfile()
         if self.__sessionCountrySettings == None:
            self.__sessionCountrySettings = self.__getCountrySettings(self.__carelinkCountry, CARELINK_LANGUAGE_EN)
         if self.__sessionMonitorData == None:
            self.__sessionMonitorData = self.__getMonitorData()
      
         # Set login success if everything was ok:
         if self.__sessionUser != None and self.__sessionProfile != None and self.__sessionCountrySettings != None and self.__sessionMonitorData != None:
            lastLoginSuccess = True
            log.info("Login successful")
         
      except Exception as e:
         printdbg(e)
         self.__lastErrorMessage = e
         log.info("Login failed with exception")

      self.__loginInProcess = False
      self.__loggedIn = lastLoginSuccess

      return lastLoginSuccess


   def __refreshToken(self, token):
      printdbg("__refreshToken()")
      log.info("Trying to refresh token")
      
      if token == None:
         printdbg("__refreshToken() no token to refresh")
         log.info("No token to refresh")
         return False
      
      success = True
      url = "https://" + self.__careLinkServer() + "/patient/sso/reauth"
      headers = self.__commonHeaders
      headers["Accept"] = "application/json, text/plain, */*"
      headers["Authorization"] = "Bearer " + token
      try:
         response = self.__httpClient.post(url, headers = headers, data = 0)
         self.__lastResponseCode = response.status_code
         if response.ok:
            printdbg("__refreshToken() success")
            log.info("Token successfully refreshed")
         else:
            printdbg(response.status_code)
            raise ValueError("session post response is not OK")            
      except Exception as e:
         printdbg(e)
         printdbg("__refreshToken() failed")
         log.info("Failed to refresh token")
         success = False
      return success


   def __getAuthorizationToken(self):
      auth_token = self.__httpClient.cookies.get(CARELINK_AUTH_TOKEN_COOKIE_NAME)
      auth_token_validto = self.__httpClient.cookies.get(CARELINK_TOKEN_VALIDTO_COOKIE_NAME)
      
      # New token is needed:
      # a) no token or about to expire => execute authentication
      # b) last response 401
      if auth_token == None or auth_token_validto == None or \
         self.__lastResponseCode in [401,403] or \
         (datetime.strptime(auth_token_validto, '%a %b %d %H:%M:%S UTC %Y') - datetime.utcnow()) < timedelta(seconds=10*60):
         
         printdbg("now: %s" % datetime.utcnow())
         # Try to refresh token
         if not self.__refreshToken(auth_token):
            # Refresh failed, execute new login process
            if self.__loginInProcess:
               printdbg("loginInProcess")
               return None
            if not self.__executeLoginProcedure():
               printdbg("__executeLoginProcedure failed")
               return None
         #printdbg("auth_token\n%s\n" % self.__httpClient.cookies.get(CARELINK_AUTH_TOKEN_COOKIE_NAME))
         printdbg("auth_token_validto = " + self.__httpClient.cookies.get(CARELINK_TOKEN_VALIDTO_COOKIE_NAME))
         log.info("New token is valid until " + self.__httpClient.cookies.get(CARELINK_TOKEN_VALIDTO_COOKIE_NAME))

      # there can be only one
      return "Bearer " + self.__httpClient.cookies.get(CARELINK_AUTH_TOKEN_COOKIE_NAME)


   # Wrapper for data retrival methods
   def getRecentData(self):
      # Force login to get basic info
      if self.__getAuthorizationToken() != None:
         if self.__carelinkCountry == "us" or "BLE" in self.__sessionMonitorData["deviceFamily"]:
            role = "carepartner" if self.__sessionUser["role"] in ["CARE_PARTNER","CARE_PARTNER_OUS"] else "patient"
            patient = self.__carelinkPatient
            return self.__getConnectDisplayMessage(self.__sessionProfile["username"], role, patient, self.__sessionCountrySettings["blePereodicDataEndpoint"])
         else:
            return self.__getLast24Hours()
      else:
         return None


   # Authentication methods
   def login(self):
      if not self.__loggedIn:
         self.__executeLoginProcedure()
         printdbg("now: %s" % datetime.utcnow())
         #printdbg("auth_token\n%s\n" % self.__httpClient.cookies.get(CARELINK_AUTH_TOKEN_COOKIE_NAME))
         printdbg("auth_token_validto = " + self.__httpClient.cookies.get(CARELINK_TOKEN_VALIDTO_COOKIE_NAME))
         log.info("New token is valid until " + self.__httpClient.cookies.get(CARELINK_TOKEN_VALIDTO_COOKIE_NAME))
      return self.__loggedIn


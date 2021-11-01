# Carelink Connect API

## Random notes from Github



### Discussion

https://github.com/nightscout/minimed-connect-to-nightscout/issues/11



### API endpoints

1. `https://carelink.minimed.com/patient/users/me/profile` provides profile information, critically a field called `username` (presumably the same as what was used to log in?)
2. `https://carelink.minimed.com/patient/countries/settings?countryCode=us&language=en` fetching this url provides an object with property `blePereodicDataEndpoint`, in this case: `blePereodicDataEndpoint: "https://clcloud.minimed.com/connect/v2/display/message" `
3. `https://carelink.minimed.com/patient/users/me` fetching this URL after authorized provides a `role` == `CARE_PARTNER` in the case I'm looking at.
4. `POST` to `https://clcloud.minimed.com/connect/v2/display/message` with a payload of eg `{ username: "loginuser", role: "carepartner" }` finally gives us all the data we expect
5. In the US, role can be `PATIENT`, and in EU, it may be `PATIENT_OUS` when fetching from `/me`.

 

### User roles

I see: there are patient roles and then "Care Partner" roles.  Care  partner roles must post their authorized role and username to the `blePereodicDataEndpoint` to get data, otherwise patients can poll their own `/patient/connect/data?cpSerialNumber=NONE&msgType=last24hours&requestTime=`?  That's my current theory, anyway. I still don't quite understand the Careportal Partner vs Connect Patient concepts fully.  https://www.youtube.com/watch?v=whTzTItL_i0

in addition there seem to be a whole host of rules attached to these roles.  I can see at least `PATIENT`, `PATIENT_OUS`, and `CARE_PARTNER` and that the behavior is different.  It looks like patients cannot  access real-time web carelink display unless the mobile app is enabled  and installed and linked to the account.
 However, the carelink patient credentials cannot be used in the app.   Rather, in order to activate the mobile app, you must sign up for a new  carepartner credentials in the mobile app, and only in the mobile app.   From what I can see, it's not possible to create a carepartner in  carelink web portal?

This is part of what confuses me, there is a way to link different  accounts together for the purposes of sharing.  It looks like the  minimum path in order to "share with yourself" is to create both  carepartner credentials as well as patient carelink credentials.  It's  important to note that these credentials require different behaviors.  mmconnnect only works with "patient carelink credentials", and doesn't  yet know how to use carepartner credentials.  It looks like the  self-patient carelink credential access is mediated by installation of  the mobile and linking the new carepartner account to an existing  careportal patient account.  According to the youtube video, a similar  flow is required for each carepartner.

There are other rules as well, it looks like the countrycode matters  quite a bit: the patient careportal and carepartner accounts must share  the same countrycode.  Medtronic only supports Followers inside the same country.

Finally, the new Carelink interfaces include mock or stub responses  on some endpoints, it looks like specifically aimed at preventing things depending on the results from crashing while yielding no data.  We'll  need continued analysis to really gather the full requirements.

Right now it looks like the most reliable mechanism is going to be:

- use credentials in 5 step process to establish initial cookie/token

- lookup 

  ```
  /patient/users/me
  ```

   to find the  

  ```
  role
  ```

   is set to 

  ```
  CARE_PARTNER
  ```

  .

  - if `role == 'CARE_PARTNER` then `GET` `/patient/countries/settings?countryCode=us&language=en` with correct parameters and set the json url to the result of the property `blePereodicDataEndpoint` in the response.
  - else set the json url to `/patient/connect/data` ( role should be `PATIENT` or `PATIENT_OUS`)
  - fetch data using json url
  - refresh token using token url

It looks like an approach like this should work more consistently  without worrying as much about which credentials are used, so long as  the countrycode matches.  Unfortunately, attempting all country codes  could result in locking accounts or worse, so users will need to know  and correctly indicate the countrycode of the original patient account  at multiple points in the workflow.



### Summary

CareLink uses OAuth since June 2020, which was implemented in minimed-connect-to-nightscout: [#2](https://github.com/nightscout/minimed-connect-to-nightscout/pull/2)

I have also used the same method in the CareLink Follower xDrip+  datasource although I still haven't implemented the refresh token (I  always do a new login, when the old token is not working anymore): [NightscoutFoundation/xDrip#1649](https://github.com/NightscoutFoundation/xDrip/pull/1649)

The difference with the new devices is that the data of the last 24 hours is not provided anymore by the `/patient/connect/data` endpoint of CareLink MiniMed servers, but by the `blePereodicDataEndpoint` in the country settings response of the `/patient/countries/settings` CareLink MiniMed endpoint.
 The information for pulling the US data was already provided by Ben in his previous comments:
 [#11 (comment)](https://github.com/nightscout/minimed-connect-to-nightscout/issues/11#issuecomment-774228928)
 [#11 (comment)](https://github.com/nightscout/minimed-connect-to-nightscout/issues/11#issuecomment-774511043)
 This pull logic is based on the US version of the online CareLink Connect webapp, which works with 770G pumps.

The last open question was just how it works outside the US, because  the online CareLink Connect webapp doesn't support the new pumps, it  still uses the old `/patient/connect/data` endpoint. It turned out, that `blePereodicDataEndpoint` information is also provided by the `/patient/countries/settings` endpoint outside the US too and it also works: the endpoint provides the data of the last 24 hours of the new 7xxG pump models.



### Implementation

#### Java

https://github.com/benceszasz/CareLinkJavaClient



### Data fields

| Field                                     | Value                                                        |
| ----------------------------------------- | ------------------------------------------------------------ |
| timeToNextCalibHours                      | 0,1,...,12                                                   |
| timeToNextCalibrationMinutes              | 0,1,2,...                                                    |
| sensorState                               | "CALIBRATION_REQUIRED", "SG_BELOW_40_MGDL","DO_NOT_CALIBRATE","CHANGE_SENSOR",WARM_UP","NO_ERROR_MESSAGE" |
| calibStatus                               | "DUENOW", "LESS_THAN_TWELVE_HRS"                             |
| lastSGTrend                               | "NONE","UP","DOUBLE_UP",...                                  |
| bgUnits                                   | "MGDL", "MMOL"?                                              |
| therapyAlgorithmState/autoModeShieldState | "FEATURE_OFF","AUTO_BASAL","SAFE_BASAL" (when waiting for calibration) |
| therapyAlgorithmState/safeBasalDuration   | minutes to exit from auto                                    |


@echo off
setlocal enableextensions enabledelayedexpansion

if "%TWS_MAJOR_VRSN%"=="" set TWS_MAJOR_VRSN=1037
if "%TRADING_MODE%"=="" set TRADING_MODE=paper
if "%TWOFA_TIMEOUT_ACTION%"=="" set TWOFA_TIMEOUT_ACTION=exit
if "%IBC_PATH%"=="" (
    echo Missing required environment variable IBC_PATH
    exit /B 1
)
if "%IBC_CONFIG%"=="" (
    echo Missing required environment variable IBC_CONFIG
    exit /B 1
)
if "%TWS_PATH%"=="" set TWS_PATH=C:\Jts
if "%IBC_LOG_PATH%"=="" set IBC_LOG_PATH=%IBC_PATH%\Logs
if "%HIDE%"=="" set HIDE=

set CONFIG=%IBC_CONFIG%
set TWS_SETTINGS_PATH=
set LOG_PATH=%IBC_LOG_PATH%
set TWSUSERID=
set TWSPASSWORD=
set FIXUSERID=
set FIXPASSWORD=
set JAVA_PATH=

set APP=TWS
set TITLE=IBC (%APP% %TWS_MAJOR_VRSN%)
if /I "%HIDE%" == "YES" (
    set MIN=/Min
) else if /I "%HIDE%" == "TRUE" (
    set MIN=/Min
) else (
    set MIN=
)

if /I "%~1" == "/INLINE" (
    "%IBC_PATH%\scripts\DisplayBannerAndLaunch.bat" %~2
) else (
    start "%TITLE%" %MIN% "%IBC_PATH%\scripts\DisplayBannerAndLaunch.bat" %~1
)
exit /B

@ECHO OFF
chcp 65001 >nul
SET PATH=C:\Program Files\Atmel\AVR Tools\STK500;%PATH%

avrdude -p atmega328p -c arduino -P COM5 -b 115200 -U flash:w:"F:/CPU150/HEX_AKN1(10-25)/akn1_10_25.hex":i

PAUSE

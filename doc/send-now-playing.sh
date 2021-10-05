#!/bin/sh

ssh klangbecken@vm-0020.vm-admin.int.rabe.ch -p 8093 'cat | sed -e "s/&/&amp;/" > Eingang/now-playing.xml' <<EOF
<?xml version="1.0"?>
<now_playing playing="1" timestamp="$(date -Iseconds | cut -b-19)">
  <song timestamp="$(date -Iseconds | cut -b-19)">
    <title><![CDATA[$1]]></title>
    <artist><![CDATA[$2]]></artist>
    <album/>
    <genre>Other</genre>
    <kind>MPEG-Audiodatei</kind>
    <track>1</track>
    <numTracks/>
    <year></year>
    <comments/>
    <time>100</time>
    <bitrate>320</bitrate>
    <rating/>
    <disc/>
    <numDiscs/>
    <playCount>$3</playCount>
    <compilation/>
    <composer/>
    <grouping/>
    <urlSource/>
    <file/>
    <artworkID/>
  </song>
</now_playing>
EOF

# ================================================= #
# SETTINGS                                          #
# ================================================= #

set("log.file", true)
set("log.file.path","<syslogdir>/<script>.log")
set("log.stdout", false)
set("server.telnet", false)
set("server.telnet.port", 1234)
set("log.level", 3)

# set("log.syslog.facility","DAEMON")
# set("log.syslog.program","liquidsoap")
# set("log.unix_timestamps",false)

set("server.socket", true)
#set("server.socket.path", "/tmp/klangbecken.sock")
#set("server.socket.path","<sysrundir>/<script>.sock")
#set("server.socket.permissions",384)
#set("server.timeout",30.)

#set("init.daemon.pidfile",true)
#set("init.daemon.pidfile.path","<sysrundir>/<script>.pid")

#set("harbor.bind_addr","0.0.0.0")
#set("harbor.max_connections",2)
#set("harbor.reverse_dns",true)

# Get the Klangbecken data directory
data_dir = getenv("KLANGBECKEN_DATA")
if not is_directory(data_dir) then
    log(level=2, "ERROR: Cannot find data directory: " ^ data_dir)
    shutdown()
end

SAEMUBOX_KLANGBECKEN_ID = 1

# ================================================= #
# PLAYLISTS                                         #
# ================================================= #

# Priority playlist
prio = playlist.once(id="prio", reload_mode="watch", path.concat(data_dir, "prio.m3u"))

# Music playlist
music = playlist(id="music", mode="randomize", reload_mode="watch",  path.concat(data_dir, "music.m3u"))

# Jingles playlist
jingles = playlist(id="jingles", mode="randomize", reload_mode="watch", path.concat(data_dir, "jingles.m3u"))
# Convert mono jingles to stereo
jingles = audio_to_stereo(jingles)


# ================================================= #
# INSERT JINGLE EVERY 15 MINUTES                    #
# ================================================= #

insert_jingle = ref false

def jingle_timeout() =
  jingle_times = [5m0s, 20m0s, 35m0s, 50m0s]
  if list.fold(fun (a,b) -> a or b, false, jingle_times) then
    log('Jingle up next')
    insert_jingle := true
  end
  1.0
end
add_timeout(0.0, jingle_timeout)

def check_jingle() =
  if (!insert_jingle) then
    insert_jingle := false
    true
  else
    false
  end
end

radio = switch(id="radio", [
  (check_jingle, jingles),
  ({true}, music),
])


# ================================================= #
# PLAY FROM PRIORITY PLAYLIST IF AVAILABLE          #
# ================================================= #

radio = fallback([prio, radio])


# ================================================= #
# REGISTER EXTERNAL RESTART COMMAND                 #
# ================================================= #

restart = ref true
current_saemubox_id = ref 1

def set_saemubox_id_fun(id) =
  current_saemubox_id := int_of_string(id)
  onair_path = path.concat(data_dir, 'onair.json')
  if !current_saemubox_id == SAEMUBOX_KLANGBECKEN_ID then
    log("Starting Klangbecken")
    restart := true
    source.skip(radio)
    system("echo true > #{onair_path}")
    "Klangbecken started"
  else
    system("echo false > #{onair_path}")
    "Klangbecken stopped"
  end
end

server.register(namespace='klangbecken',
                description="Set the current Saemubox channel id",
                usage="set_saemubox_id ID",
                "set_saemubox_id",
                set_saemubox_id_fun)

# Have restart delay and fade dynamically reconfigurable
# for debugging purpose
restart_delay = interactive.float("restart.delay", 1.0)
restart_fade = interactive.float("restart.fade", 1.0)

def trans(old, new) =
  if !restart and source.id(new) == "radio" then
    restart := false
    sequence([blank(duration=restart_delay()),
              fade.initial(duration=restart_fade(), new)])
  else
    new
  end
end

radio = fallback(track_sensitive=false,
                 transitions=[trans],
                 [radio, blank(id="blank")])


# ================================================= #
# LOGGING METADATA                                  #
# ================================================= #
have_metadata = ref false
artist = ref ''
title = ref ''
length = ref 0

def log_md_func(m) =
  log("Metadata: ")
  list.iter(fun (el) -> log("   #{fst(el)}: #{snd(el)}"), m)

  # Print filename to stdout
  print('Playing: ', newline=false)
  print(m['filename'])
  have_metadata := true
  artist := m['artist']
  title := m['title']
  length := int_of_float(float_of_string(m['cue_out']) - float_of_string(m['cue_in']))
end
radio = on_track(log_md_func, radio)

def upload_metadata() =
  have_metadata := false
  system("ssh endlosplayer@10.1.1.71 'cat > Eingang/now-playing-new.xml' <<EOF
<?xml version=\"1.0\"?>
<now_playing playing=\"1\" timestamp=\"$(date -Iseconds)\">
  <song timestamp=\"$(date -Iseconds)\">
    <title>#{!title}</title>
    <artist>#{!artist}</artist>
    <album/>
    <genre>Other</genre>
    <kind>MPEG-Audiodatei</kind>
    <track>1</track>
    <numTracks/>
    <year></year>
    <comments/>
    <time>#{!length}</time>
    <bitrate>320</bitrate>
    <rating/>
    <disc/>
    <numDiscs/>
    <playCount>1</playCount>
    <compilation/>
    <composer/>
    <grouping/>
    <urlSource/>
    <file/>
    <artworkID/>
  </song>
</now_playing>
EOF")
end

exec_at(pred=fun() -> !have_metadata, upload_metadata)


# ================================================= #
# AUDIO PROCESSING                                  #
# ================================================= #

# Cut silence at beginning and end
radio = cue_cut(radio, cue_in_metadata="cue_in", cue_out_metadata="cue_out")
# Apply calculated replay gain
radio = amplify(1., override="replaygain_track_gain", radio)
# Moderate cross-fading
radio = crossfade(start_next=.5, fade_out=1., fade_in=0., radio)
# Create some additional head room
radio = amplify(0.5, radio)


# ================================================= #
# OUTPUT                                            #
# ================================================= #

output.alsa(id="out", device="default:CARD=Axia", radio)

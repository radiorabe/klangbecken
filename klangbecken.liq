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
DATA_DIR = getenv("KLANGBECKEN_DATA")
if not is_directory(DATA_DIR) then
    log(level=2, "ERROR: Cannot find data directory: " ^ DATA_DIR)
    shutdown()
end

# Get the klangecken command
CMD_PATH = getenv("KLANGBECKEN_PATH")

# Get alsa device
ALSA_DEVICE = getenv("KLANGBECKEN_ALSA_DEVICE")


# ================================================= #
# PLAYLISTS                                         #
# ================================================= #

# Priority playlist for 'play next' feature
prio = playlist.once(id="prio", reload_mode="watch", path.concat(DATA_DIR, "prio.m3u"))
# Cut silence at start and end
prio = cue_cut(prio, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Music playlist
music = playlist(id="music", mode="randomize", reload_mode="watch",  path.concat(DATA_DIR, "music.m3u"))
# Cut silence at start and end
music = cue_cut(music, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Classics playlist
classics = playlist(id="classics", mode="randomize", reload_mode="watch",  path.concat(DATA_DIR, "classics.m3u"))
# Cut silence at start and end
classics = cue_cut(classics, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Jingles playlist
jingles = playlist(id="jingles", mode="randomize", reload_mode="watch", path.concat(DATA_DIR, "jingles.m3u"))
# Convert mono jingles to stereo
jingles = audio_to_stereo(jingles)
# Cut silence at start and end
jingles = cue_cut(jingles, cue_in_metadata="cue_in", cue_out_metadata="cue_out")


# ================================================= #
# MIX MUSIC AND CASSICS                             #
# ================================================= #

music = random(weights=[5, 1], [music, classics])


# ================================================= #
# PLAY FROM PRIORITY PLAYLIST IF AVAILABLE          #
# ================================================= #

music = fallback([prio, music])


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
# REGISTER EXTERNAL RESTART COMMAND                 #
# ================================================= #

restart = ref true
onair = ref false

def onair_func(state) =
  onair := bool_of_string(string.case(state))
  if !onair then
    log("Starting Klangbecken")
    restart := true
    source.skip(radio)
    "Klangbecken started"
  else
    log("Stopping Klangbecken")
    system("#{CMD_PATH} playlog -d #{DATA_DIR} --off")
    "Klangbecken stopped"
  end
end

server.register(namespace='klangbecken',
                description="Control, if the player is on air",
                usage="onair (true|false)",
                "onair",
                onair_func)

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

have_new_metadata = ref false
filename = ref ''

def log_metadata_func(m) =
  # Log to stdout
  print('Playing: ', newline=false)
  print(m['filename'])

  if !onair then
    # Prepare play logger
    have_new_metadata := true
    filename := m['filename']
  end
end
radio = on_track(log_metadata_func, radio)

def run_play_logger() =
  have_new_metadata := false
  system("#{CMD_PATH} playlog -d #{DATA_DIR} #{!filename}")
end

# Run the logging command in the background, not to lock up the player
exec_at(pred=fun() -> !have_new_metadata, run_play_logger)


# ================================================= #
# AUDIO PROCESSING                                  #
# ================================================= #

# Apply calculated replay gain
radio = amplify(1., override="replaygain_track_gain", radio)
# Moderate cross-fading
radio = crossfade(start_next=.5, fade_out=1., fade_in=0., radio)
# Create some additional head room
radio = amplify(0.5, radio)


# ================================================= #
# OUTPUT                                            #
# ================================================= #

output.alsa(id="out", device=ALSA_DEVICE, radio)

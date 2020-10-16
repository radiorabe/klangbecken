# ================================================= #
# SETTINGS                                          #
#                                                   #
# Environment Variables:                            #
#   - KLANGBECKEN_ALSA_DEVICE                       #
#     ALSA device to send sound to                  #
#   - KLANGBECKEN_DATA                              #
#     Directory with data                           #
#   - KLANGBECKEN_PATH                              #
#     Path to klangbecken.py                        #
#   - KLANGBECKEN_SOCKET_PATH                       #
#     Path to socket to listen on                   #
# ================================================= #

# set setting to getenv(var) if set
def set_if_env(setting, var) =
  if getenv(var) != "" then
    set(setting, getenv(var))
  end
end

# return value of environment variable if set, otherwise fallback
def getenv_fallback(var, fallback) =
  if getenv(var) != "" then
    getenv(var)
  else
    fallback
  end
end

# log file
set("log.file", false)
set("log.stdout", true)
set("server.telnet", false)
set("server.telnet.port", 1234)
set("log.level", 3)

# socket
set("server.socket", true)
set_if_env("server.socket.path", "KLANGBECKEN_SOCKET_PATH")

# Get the Klangbecken data directory
DATA_DIR = getenv_fallback("KLANGBECKEN_DATA", "data")
if not is_directory(DATA_DIR) then
    log(level=2, "ERROR: Cannot find data directory: " ^ DATA_DIR)
    shutdown()
end
INDEX = path.concat(DATA_DIR, "index.json")

# Get the klangecken command
CMD_PATH = getenv_fallback("KLANGBECKEN_PATH", "./klangbecken.py")

# Get the alsa device
ALSA_DEVICE = getenv_fallback("KLANGBECKEN_ALSA_DEVICE", "default")

# ================================================= #
# PLAYLISTS                                         #
# ================================================= #

# calculate waiting time for repeating a track depending on its playlist
def calc_wait(playlist) =
  if playlist == "music" then 259200.0 # 3 days
  elsif playlist == "classics" then 86400.0 # 1 day
  elsif playlist == "jingles" then 3600.0 # 1 hour
  else 0.0 end
end

# check if track was played recently
skipped = ref 0
def check_next_func(r) = 
  metadata = request.metadata(r)
  filename = request.filename(r)

  last_play = float_of_string(metadata["last_play"])
  if last_play == 0.0 then
    skipped := 0
    log("track was never played before: #{filename}", label="check_next_func")
    true
  else
    diff = gettimeofday() - last_play
    filename_split = string.split(filename, separator="/")
    # the playlist folder is the penultimate part of the file path
    playlist = list.nth(filename_split, list.length(filename_split)-2, default="")
    if diff < calc_wait(playlist) then
      skipped := !skipped + 1
      log("track was recently played: #{filename} (#{diff} seconds ago)", label="check_next_func")
      if !skipped >= 10 then
        skipped := 0
        log("too many skipped tracks, playing #{filename} anyway", label="check_next_func")
        true
      else
        false
      end
    else
      skipped := 0
      log("next: #{filename} (track was last played #{diff} seconds ago)", label="check_next_func")
      true
    end
  end
end

# Priority playlist for 'play next' feature
prio = playlist.once(id="prio", reload_mode="watch", path.concat(DATA_DIR, "prio.m3u"))
# Cut silence at start and end
prio = cue_cut(prio, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Music playlist
music = playlist(id="music", mode="random", reload_mode="watch",
                 check_next=check_next_func, path.concat(DATA_DIR, "music.m3u"))
# Cut silence at start and end
music = cue_cut(music, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Classics playlist
classics = playlist(id="classics", mode="random", reload_mode="watch",
                    check_next=check_next_func, path.concat(DATA_DIR, "classics.m3u"))
# Cut silence at start and end
classics = cue_cut(classics, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Jingles playlist
jingles = playlist(id="jingles", mode="random", reload_mode="watch",
                   check_next=check_next_func, path.concat(DATA_DIR, "jingles.m3u"))
# Convert mono jingles to stereo
jingles = audio_to_stereo(jingles)
# Cut silence at start and end
jingles = cue_cut(jingles, cue_in_metadata="cue_in", cue_out_metadata="cue_out")


# ================================================= #
# MIX MUSIC AND CLASSICS                            #
# ================================================= #

music = random(weights=[5, 1], [music, classics])


# ================================================= #
# INSERT JINGLE AND PRIO WHEN NEEDED                #
# ================================================= #

insert_jingle = ref false
onair = ref false

def jingle_timeout() =
  jingle_times = [5m0s, 20m0s, 35m0s, 50m0s]
  if list.fold(fun (a,b) -> a or b, false, jingle_times) then
    log('Jingle up next')
    insert_jingle := true
  end
  1.0
end
add_timeout(0.0, jingle_timeout)

radio = switch(id="radio", [
  ({!insert_jingle}, jingles),
  ({!onair}, prio),
  ({true}, music),
])

def on_track_func(m) =
  # Reset jingle playing flag
  insert_jingle := false

  # Clear prio playlist if on air
  if !onair and m['source'] == "prio" then
    log("resetting prio playlist", label="on_track_func")
    system("echo > #{DATA_DIR}/prio.m3u")
  end
end
radio = on_track(on_track_func, radio)


# ================================================= #
# REGISTER EXTERNAL RESTART COMMAND                 #
# ================================================= #

restart = ref true

def onair_func(state) =
  onair := bool_of_string(string.case(state))
  if !onair then
    log("starting Klangbecken", label="onair_func")
    restart := true
    source.skip(radio)
    "Klangbecken started"
  else
    log("stopping Klangbecken", label="onair_func")
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
  log('Playing: #{m["filename"]}', label="log_metadata_func")

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


# ================================================= #
# OUTPUT                                            #
# ================================================= #

output.alsa(id="out", bufferize=false, device=ALSA_DEVICE, radio)
